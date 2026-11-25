from django.db import migrations, models
from django.core.validators import MinValueValidator
class Migration(migrations.Migration):
    dependencies=[('promotions','0001_initial')]
    operations=[migrations.AlterField(model_name=model,name=field,field=models.DecimalField(max_digits=18,decimal_places=4,default=0,validators=[MinValueValidator(0)])) for model,field in [('offer','discount_amount'),('redemption','discount')]]
