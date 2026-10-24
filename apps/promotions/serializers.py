from rest_framework import serializers
from .models import Offer
class OfferSerializer(serializers.ModelSerializer):
    class Meta:
        model=Offer
        fields=['id','name','code','description','offer_type','status','starts_at','ends_at','buy_quantity','get_quantity','discount_percentage','discount_amount','repeatable','automatic','priority','products','branches']
    def validate(self,data):
        kind=data.get('offer_type',getattr(self.instance,'offer_type',None))
        if kind=='BUY_X_GET_Y' and (data.get('buy_quantity',getattr(self.instance,'buy_quantity',1))<1 or data.get('get_quantity',getattr(self.instance,'get_quantity',1))<1):raise serializers.ValidationError('Buy and reward quantities must be positive.')
        if kind=='PERCENTAGE_DISCOUNT' and not 0<=data.get('discount_percentage',getattr(self.instance,'discount_percentage',0))<=100:raise serializers.ValidationError('Percentage must be between 0 and 100.')
        start=data.get('starts_at',getattr(self.instance,'starts_at',None));end=data.get('ends_at',getattr(self.instance,'ends_at',None))
        if start and end and end<=start:raise serializers.ValidationError('End must be after start.')
        user=self.context.get('request').user if self.context.get('request') else None
        if user:
            for field in ('products','branches'):
                for item in data.get(field,[]):
                    if item.organization_id!=user.organization_id:raise serializers.ValidationError({field:'Selection must belong to your organization.'})
                    if field=='branches' and (item.kind!='Branch' or item.isVirtual):raise serializers.ValidationError({field:'Select physical branches only.'})
        return data
