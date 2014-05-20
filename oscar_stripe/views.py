import logging
logger = logging.getLogger(__name__)
from decimal import ROUND_FLOOR, Decimal as D

from django.conf import settings
from django.db.models import get_model
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar_stripe.facade import Facade

from . import PAYMENT_METHOD_STRIPE, PAYMENT_EVENT_PURCHASE, STRIPE_EMAIL, STRIPE_TOKEN

import forms

Partner = get_model('partner', 'Partner')
SourceType = get_model('payment', 'SourceType')
Source = get_model('payment', 'Source')


class PaymentDetailsView(CorePaymentDetailsView):

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(PaymentDetailsView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super(PaymentDetailsView, self).get_context_data(**kwargs)
        if self.preview:
            ctx['stripe_token_form'] = forms.StripeTokenForm(self.request.POST)
            ctx['order_total_incl_tax_cents'] = (
                ctx['order_total'].incl_tax * 100
            ).to_integral_value()
        else:
            ctx['stripe_publishable_key'] = settings.STRIPE_PUBLISHABLE_KEY
        return ctx

    def handle_payment(self, order_number, total, **kwargs):
        """
        Use the basket object that is passed in through kwargs
        to generate a mapping of line items to partners so we can
        generate separate charges to different vendors.
        """
        # set up the default partner
        default_partner = self.get_default_partner(**kwargs)

        partners = {
            default_partner: {
                'stripe': self.get_stripe_token(default_partner),
                'charges': [total.tax, kwargs['shipping_cost']],
            }
        }
        # Get all items and partners within the basket
        for line in self.request.basket.all_lines():
            partner = line.stockrecord.partner

            # handle the default_parnter separately
            if partner not in partners and partner != default_partner:
                stripe_token = self.get_stripe_token(partner)

                partners[partner] = {
                    'stripe': stripe_token,
                    'charges': []
                }

            default_charge, partner_charge = self.split_charge(line)

            # default partner automatically gets the default_charge
            partners[default_partner]['charges'].append(default_charge)

            # if the partner has a stripe token, send them the partner_charge
            if partners[partner]['stripe']:
                partners[partner]['charges'].append(partner_charge)
            # if the partner doesn't have a stripe token, send them the partner_charge
            else:
                partners[default_partner]['charges'].append(partner_charge)

        chargeable_partners = []
        for partner, info in partners.items():
            if len(info['charges']):
                chargeable_partners.append({partner: info})

        facades = []
        # Attempt to pull the access token from the auth
        # Stripe account, defaulting to the key that is found
        # in the settings file.
        for index, info in enumerate(chargeable_partners):
            try:
                # We want to generate the charges first without capturing
                # them (actually charging them). This allows us to confirm
                # that everything is setup fine on the Stripe side after
                # moving through all of the line items in the basket. If
                # we find a single charge misbehaving, we can handle it
                # separately.
                partner = info.keys()[0]
                stripe_access_token = info[partner]['stripe']
                charges = info[partner]['charges']

                # this partner doesn't have any lines, probably because they don't
                # have stripe information, so skip them.
                if len(charges) == 0:
                    continue

                total = sum([charge for charge in charges if charge])

                facade = Facade(api_key=stripe_access_token)
                stripe_ref = facade.charge(
                    order_number,
                    total,
                    card=self.request.POST[STRIPE_TOKEN],
                    description=self.payment_description(order_number, total, **kwargs),
                    metadata=self.payment_metadata(order_number, total, **kwargs))
                facades.append(facade)
            except Exception, e:
                logger.error(e, exc_info=True, extra={
                })
                raise

        # Once all the stripe charges have been created we can
        # then go ahead and capture them (actually charge them).
        for facade in facades:
            try:
                # Figure out what the application_fee might be here
                facade.capture()
                source_type, __ = SourceType.objects.get_or_create(name=PAYMENT_METHOD_STRIPE)
                source = Source(
                    source_type=source_type,
                    currency=settings.STRIPE_CURRENCY,
                    amount_allocated=facade.total,
                    amount_debited=facade.total,
                    reference=facade.charge_object.id)

                self.add_payment_source(source)
                self.add_payment_event(PAYMENT_EVENT_PURCHASE, facade.total)
            except Exception, e:
                logger.error(e, exc_info=True, extra={
                })
                raise

    def split_charge(self, line):
        stockrecord = line.stockrecord
        return (
            (stockrecord.price_excl_tax - stockrecord.cost_price) * line.quantity,
            stockrecord.cost_price * line.quantity
        )

    def get_stripe_token(self, partner):
        stripe_owner = partner.users.filter(social_auth__provider='stripe').all()
        if len(stripe_owner) == 1:
            stripe_info = stripe_owner.get().social_auth.get(provider='stripe')

            if 'access_token' in stripe_info.tokens:
                return stripe_info.tokens['access_token']
        return None

    def get_default_partner(self, **kwargs):
        partner_code = kwargs.get('default_partner_code', None)
        if not partner_code:
            return None

        try:
            return Partner.objects.get(code=partner_code)
        except Partner.DoesNotExist, e:
            logger.error(e, exc_info=True, extra={
                'partner_code': partner_code,
            })
            raise

    def payment_description(self, order_number, total, **kwargs):
        return self.request.POST[STRIPE_EMAIL]

    def payment_metadata(self, order_number, total, **kwargs):
        return {'order_number': order_number}
