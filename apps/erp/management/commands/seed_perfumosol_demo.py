from decimal import Decimal
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.contrib.auth import get_user_model
from apps.accounts.models import Organization
from apps.erp import models as m,services as s
from apps.erp.workflow import save_percentage_formula,save_product

class Command(BaseCommand):
    help='Create documented Perfumosol demonstration masters and opening stock once; reruns preserve existing data.'
    def add_arguments(self,parser):
        parser.add_argument('--username',help='Existing owner/superuser to assign to the demo organization.')
    @transaction.atomic
    def handle(self,*args,**opts):
        org,_=Organization.objects.get_or_create(name='Perfumosol Demonstration')
        Organization.objects.select_for_update().get(pk=org.pk)
        users=get_user_model()
        if opts.get('username'):
            try: user=users.objects.get(username=opts['username'])
            except users.DoesNotExist: raise CommandError('Create this user first.')
            if not user.is_superuser and user.role!='owner': raise CommandError('Use an owner or superuser.')
            if user.organization_id and user.organization_id!=org.pk: raise CommandError('User belongs to another organization; no changes made.')
            user.organization=org;user.role='owner';user.save()
        else:
            user,created=users.objects.get_or_create(username='perfumosol_demo',defaults={'organization':org,'role':'owner','is_active':False})
            if user.organization_id!=org.pk: raise CommandError('Demo username already belongs to another organization.')
            if created: user.set_unusable_password();user.save()
        marker='PERFUMOSOL-DEMO-v1'
        if m.Movement.objects.filter(organization=org,reference=marker).exists():
            self.stdout.write('Demo data already seeded; balances and transactions were not changed.');return
        def master(model,key,defaults): return model.objects.get_or_create(organization=org,**key,defaults=defaults)[0]
        branches=[master(m.Location,{'code':f'BR0{i}'},dict(name=f'Perfumosol {name} Branch',kind='Branch',location='Demonstration data')) for i,name in enumerate(['Main','Production'],1)]
        warehouses=[master(m.Location,{'code':f'WH0{i}'},dict(name=name,kind='Warehouse',location='Demonstration data')) for i,name in enumerate(['Main Raw Material Warehouse','Production Raw Material Warehouse','Main Finished Goods Warehouse','Production Finished Goods Warehouse'],1)]
        oils=['Royal Oud','Sandalwood','Rose','Jasmine','Vanilla','Amber','White Musk','Bergamot','Lavender','Patchouli']
        materials=[]
        for i,name in enumerate(oils,1): materials.append(master(m.Material,{'code':f'OIL{i:02}'},dict(name=f'{name} Fragrance Oil',category='Perfume Oil',unit='ml',currentCost=Decimal(str([8,6,4,5,3,6,4,3,2,5][i-1])),minStock=500,description='Demonstration data')))
        oilm=materials[:]
        solvents=[]
        for i,(name,cost) in enumerate([('Perfumery Alcohol','.25'),('Dipropylene Glycol','.5'),('Triethyl Citrate','.75')],1):
            mat=master(m.Material,{'code':f'SOL{i:02}'},dict(name=name,category='Solvent',unit='ml',currentCost=Decimal(cost),minStock=1000,description='Demonstration data'));solvents.append(mat);materials.append(mat)
        packages=[]
        names=['30 ml Glass Perfume Bottle','50 ml Glass Perfume Bottle','100 ml Glass Perfume Bottle','Fine Mist Spray Pump','Gold Perfume Cap','Black Perfume Cap','Perfume Labels','30 ml Carton','50 ml Carton','100 ml Carton']
        for i,name in enumerate(names,1):
            mat=master(m.Material,{'code':f'PKG{i:02}'},dict(name=name,category='Packaging',unit='pcs',currentCost=Decimal(str([10,12,16,3,2,2,1,4,5,6][i-1])),minStock=50,description='Demonstration data'));packages.append(mat);materials.append(mat)
        from apps.erp.category_utils import register_existing_categories
        register_existing_categories(org)
        sizes=[master(m.BottleSize,{'name':f'{volume} ml'},dict(volumeMl=volume,bottleMaterialRef=packages[i])) for i,volume in enumerate([30,50,100])]
        conc=master(m.Concentration,{'code':'EDP'},dict(name='Eau de Parfum',oilPercentage=23,description='Demonstration label; formulation controls actual percentages.'))
        for wh in warehouses[:2]:
            for mat in materials: s.post_stock(user,wh,mat,Decimal(10000 if mat.unit=='ml' else 500),'DEMO_OPENING',marker,'Demonstration opening inventory')
        for i,name in enumerate(oils[:5],1):
            frag=master(m.Fragrance,{'code':f'FR{i:02}'},dict(name=name,perfumeOilId=oilm[i-1],category='Woody' if i<3 else 'Floral',notes='Demonstration fragrance profile'))
            formula=save_percentage_formula(user,dict(code=f'FORM{i:02}',name=f'{name} EDP Liquid Recipe',fragranceId=frag.pk,version='v1.0',status='active',percentageRecipe=True,percentageIngredients=[dict(materialId=oilm[i-1].pk,percentage=18),dict(materialId=oilm[5].pk,percentage=5),dict(materialId=solvents[0].pk,percentage=75),dict(materialId=solvents[1].pk,percentage=2)]))
            save_product(user,dict(code=f'PROD{i:02}',name=f'{name} Eau de Parfum',fragranceId=frag.pk,formulaId=formula.pk,category='Perfume',description='Demonstration product',status='active',variants=[dict(sku=f'DEMO-{name.upper().replace(" ","-")}-{int(size.volumeMl)}',bottleSizeId=size.pk,concentrationId=conc.pk,fillVolumeMl=size.volumeMl,sellingPrice=Decimal(size.volumeMl)*12,additionalCost=5,minStock=10,status='active',packaging=[dict(materialId=packages[j].pk,qty=1) for j in [k,3,4,6,7+k]]) for k,size in enumerate(sizes)]))
        self.stdout.write(self.style.SUCCESS('Demonstration data created: 2 branches, 4 warehouses, 23 materials, 5 fragrances, 5 percentage recipes, 5 products and 15 variants. No finished stock is created until manufacture.'))
        self.stdout.write('Create a superuser, then rerun with --username YOUR_USERNAME to access the demo organization. No demo login password is embedded.')
