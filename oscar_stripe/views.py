import stripe
from django.conf import settings
from django.contrib import messages
from django.db.models import get_model
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView, PaymentError, UnableToTakePayment

import forms
from . import PAYMENT_METHOD_STRIPE, PAYMENT_EVENT_PURCHASE, STRIPE_EMAIL, STRIPE_TOKEN

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
            ctx['order_total_incl_tax_cents'] = (ctx['order_total'].incl_tax * 100).to_integral_value()
        else:
            ctx['stripe_publishable_key'] = settings.STRIPE_PUBLISHABLE_KEY
        return ctx

    def handle_payment_error(self, error_class, e, order_number):
        messages.error(self.request, _(
            "We experienced a problem while processing your payment. Please check your card details and try again."
            "If the problem persists, please contact us.")
        )
        raise error_class("received error(s) '%s' from stripe for transaction #%s" % (e, order_number))

    def handle_payment(self, order_number, total, **kwargs):
        stripe.api_key = settings.STRIPE_SECRET_KEY

        try:
            charge = stripe.Charge.create(amount=(total.incl_tax * 100).to_integral_value(),
                                          currency=settings.STRIPE_CURRENCY, card=self.request.POST[STRIPE_TOKEN],
                                          description=self.request.POST[STRIPE_EMAIL],
                                          metadata={'order_number': order_number})
        except stripe.CardError, e:
            self.handle_payment_error(UnableToTakePayment, (e.code, e.param, e.message), order_number)
        except stripe.InvalidRequestError, e:
            self.handle_payment_error(PaymentError, (e.param, e.message), order_number)
        except stripe.StripeError, e:
            self.handle_payment_error(PaymentError, e.message, order_number)

        source_type, __ = SourceType.objects.get_or_create(name=PAYMENT_METHOD_STRIPE)
        source = Source(source_type=source_type, currency=settings.STRIPE_CURRENCY, amount_allocated=total.incl_tax,
                        amount_debited=total.incl_tax, reference=charge.id)
        self.add_payment_source(source)

        self.add_payment_event(PAYMENT_EVENT_PURCHASE, total.incl_tax)
