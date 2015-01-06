from django.conf import settings
from oscar.apps.payment.exceptions import UnableToTakePayment, InvalidGatewayRequestError
from django.utils import timezone

import stripe
from django.db.models import get_model

Source = get_model('payment', 'Source')
Order = get_model('order', 'Order')

class Facade(object):
    def __init__(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY

    @staticmethod
    def get_friendly_decline_message(error):
        return 'The transaction was declined by your bank - please check your bankcard details and try again'

    @staticmethod
    def get_friendly_error_message(error):
        return 'An error occurred when communicating with the payment gateway.'

    def charge(self,
        order_number,
        total,
        card,
        currency=settings.STRIPE_CURRENCY,
        description=None,
        metadata=None,
        **kwargs):
        try:
            charge_and_capture_together = getattr(settings,
                "STRIPE_CHARGE_AND_CAPTURE_IN_ONE_STEP", False)
            return stripe.Charge.create(
                amount=(total.incl_tax * 100).to_integral_value(),
                currency=currency,
                card=card,
                description=description,
                metadata=(metadata or {'order_number': order_number}),
                capture = charge_and_capture_together
                **kwargs).id
        except stripe.CardError, e:
            raise UnableToTakePayment(self.get_friendly_decline_message(e))
        except stripe.StripeError, e:
            raise InvalidGatewayRequestError(self.get_friendly_error_message(e))

    def capture(self, order_number, **kwargs):
        """
        if capture is set to false in charge, the charge will only be pre-authorized
        one need to use capture to actually charge the customer
        """
        try:
            order = Order.objects.get(number=order_number)
            payment_source = Source.objects.get(order=order)
            # get charge_id from source
            charge_id = payment_source.reference
            # find charge
            charge = stripe.Charge.retrieve(charge_id)
            # capture
            charge.capture()
            # set captured timestamp
            payment_source.date_captured = timezone.now()
            payment_source.save()
        except Source.DoesNotExist:
            raise Exception("Capture Failiure could not find payment source for Order %s" % order_id)
        except Order.DoesNotExist:
            raise Exception("Capture Failiure Order %s does not exist" % order_id)