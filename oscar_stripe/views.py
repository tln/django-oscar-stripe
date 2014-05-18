import json

from django.conf import settings
from django.db.models import get_model
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar_stripe.facade import Facade

from . import PAYMENT_METHOD_STRIPE, PAYMENT_EVENT_PURCHASE, STRIPE_EMAIL, STRIPE_TOKEN

import forms

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
        facades = []
        partners = {}
        # Get all items and partners within the basket
        for line in kwargs['basket'].all_lines():
            partner = line.stockrecord.partner
            if partner not in partners:
                partners[partner] = []

            partners[partner].append(line)

        for partner, lines in partners.items():
            stripe_owner = partner.users.filter(social_auth__provider='stripe').all()

            access_token = settings.STRIPE_SECRET_KEY
            if len(stripe_owner) == 1:
                stripe_info = stripe_owner.pop().social_auth.get(provider='stripe')
                stripe_data = json.dumps(stripe_info.extra_data)

                if 'access_token' in stripe_data:
                    api_key = stripe_data['access_token']

            elif len(stripe_owner) == 0:
                pass
                # TODO: raise something
            else:
                pass
                # TODO: raise something
            try:
                for line in lines:
                    facade = Facade(api_key=access_token)
                    total = line.line_price_incl_tax * line.quantity
                    stripe_ref = facade.charge(
                        order_number,
                        total,
                        card=self.request.POST[STRIPE_TOKEN],
                        description=self.payment_description(order_number, total, **kwargs),
                        metadata=self.payment_metadata(order_number, total, **kwargs))

                    source_type, __ = SourceType.objects.get_or_create(name=PAYMENT_METHOD_STRIPE)
                    source = Source(
                        source_type=source_type,
                        currency=settings.STRIPE_CURRENCY,
                        amount_allocated=total,
                        amount_debited=total,
                        reference=stripe_ref)

                    self.add_payment_source(source)
                    self.add_payment_event(PAYMENT_EVENT_PURCHASE, total)
            except Exception, e:
                import traceback
                traceback.print_exc()
                print e
                raise e

    def payment_description(self, order_number, total, **kwargs):
        return self.request.POST[STRIPE_EMAIL]

    def payment_metadata(self, order_number, total, **kwargs):
        return {'order_number': order_number}
