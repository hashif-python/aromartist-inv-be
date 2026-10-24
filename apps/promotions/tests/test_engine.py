from decimal import Decimal
from unittest.mock import patch
from django.test import SimpleTestCase
from apps.promotions.services import calculate

class FakeRelation:
    def __init__(self,items):self.items=items
    def all(self):return self.items
class FakeOffer:
    def __init__(self,buy,get,kind='BUY_X_GET_Y',percent=0):
        self.pk='offer-1';self.buy_quantity=buy;self.get_quantity=get
        self.offer_type=kind;self.discount_percentage=Decimal(percent)
        self.repeatable=True;self.discount_amount=Decimal(0)
        self.branches=FakeRelation([])
        self.products=FakeRelation([type('Product',(),{'pk':'rose'})()])
class PromotionCalculationTests(SimpleTestCase):
    @patch('apps.promotions.services.available')
    def test_bogo_two(self,offers):
        offers.return_value=[FakeOffer(1,1)]
        result=calculate(None,type('Branch',(),{'pk':'main'})(),[{'productId':'rose','qty':2,'rate':'1000'}])
        self.assertEqual(result['discount'],Decimal('1000.00'))
    @patch('apps.promotions.services.available')
    def test_buy_two_get_one_six(self,offers):
        offers.return_value=[FakeOffer(2,1)]
        result=calculate(None,type('Branch',(),{'pk':'main'})(),[{'productId':'rose','qty':6,'rate':'800'}])
        self.assertEqual(result['discount'],Decimal('1600.00'))
    @patch('apps.promotions.services.available')
    def test_unrelated_product_not_discounted(self,offers):
        offers.return_value=[FakeOffer(1,1)]
        self.assertIsNone(calculate(None,type('Branch',(),{'pk':'main'})(),[{'productId':'musk','qty':2,'rate':'800'}]))
