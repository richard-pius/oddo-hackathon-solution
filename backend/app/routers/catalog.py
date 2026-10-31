"""
Catalog Router — Products, Variants, Plans, Tax Rules, Discount Rules
======================================================================
Admin CRUD for the product catalog. Staff can read; customers cannot
access catalog management at all (they see products through their
subscription lines).
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    User, Product, ProductVariant, SubscriptionPlan,
    TaxRule, DiscountRule, QuotationTemplate, QuotationTemplateLine,
)
from app.schemas import (
    ProductCreate, ProductUpdate, ProductOut, VariantCreate, VariantOut,
    PlanCreate, PlanUpdate, PlanOut,
    TaxRuleCreate, TaxRuleOut,
    DiscountRuleCreate, DiscountRuleOut,
    QuotationTemplateCreate, QuotationTemplateOut,
)
from app.services.auth_service import require_admin, require_staff_or_admin

router = APIRouter(prefix="/api/v1/catalog", tags=["Product Catalog"])


# ─── Products ─────────────────────────────────────────────────────────────────

@router.get("/products", response_model=list[ProductOut])
async def list_products(
    is_active: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.variants))
        .where(Product.is_active == is_active)
        .order_by(Product.name)
    )
    return result.scalars().all()


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(
        select(Product).options(selectinload(Product.variants)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(product, k, v)
    await db.commit()
    await db.refresh(product)
    return product


# ─── Variants ─────────────────────────────────────────────────────────────────

@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=status.HTTP_201_CREATED)
async def create_variant(
    product_id: int,
    data: VariantCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    variant = ProductVariant(product_id=product_id, **data.model_dump())
    db.add(variant)
    await db.commit()
    await db.refresh(variant)
    return variant


@router.get("/products/{product_id}/variants", response_model=list[VariantOut])
async def list_variants(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(
        select(ProductVariant).where(ProductVariant.product_id == product_id)
    )
    return result.scalars().all()


# ─── Plans ────────────────────────────────────────────────────────────────────

@router.get("/plans", response_model=list[PlanOut])
async def list_plans(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.name))
    return result.scalars().all()


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    plan = SubscriptionPlan(**data.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/plans/{plan_id}", response_model=PlanOut)
async def get_plan(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.put("/plans/{plan_id}", response_model=PlanOut)
async def update_plan(
    plan_id: int,
    data: PlanUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)
    await db.commit()
    await db.refresh(plan)
    return plan


# ─── Tax Rules ────────────────────────────────────────────────────────────────

@router.get("/taxes", response_model=list[TaxRuleOut])
async def list_taxes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(select(TaxRule).order_by(TaxRule.name))
    return result.scalars().all()


@router.post("/taxes", response_model=TaxRuleOut, status_code=status.HTTP_201_CREATED)
async def create_tax(
    data: TaxRuleCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    tax = TaxRule(**data.model_dump())
    db.add(tax)
    await db.commit()
    await db.refresh(tax)
    return tax


# ─── Discount Rules ──────────────────────────────────────────────────────────

@router.get("/discounts", response_model=list[DiscountRuleOut])
async def list_discounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(select(DiscountRule).order_by(DiscountRule.name))
    return result.scalars().all()


@router.post("/discounts", response_model=DiscountRuleOut, status_code=status.HTTP_201_CREATED)
async def create_discount(
    data: DiscountRuleCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Check for duplicate code
    existing = await db.execute(select(DiscountRule).where(DiscountRule.code == data.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Discount code '{data.code}' already exists")

    rule = DiscountRule(**data.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/discounts/{discount_id}", response_model=DiscountRuleOut)
async def get_discount(
    discount_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(select(DiscountRule).where(DiscountRule.id == discount_id))
    disc = result.scalar_one_or_none()
    if not disc:
        raise HTTPException(status_code=404, detail="Discount not found")
    return disc


# ─── Quotation Templates ────────────────────────────────────────────────────

@router.get("/templates", response_model=list[QuotationTemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    result = await db.execute(
        select(QuotationTemplate)
        .options(selectinload(QuotationTemplate.template_lines))
        .order_by(QuotationTemplate.name)
    )
    return result.scalars().all()


@router.post("/templates", response_model=QuotationTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: QuotationTemplateCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    template = QuotationTemplate(
        name=data.name,
        plan_id=data.plan_id,
        validity_days=data.validity_days,
        payment_terms=data.payment_terms,
        notes=data.notes,
    )
    db.add(template)
    await db.flush()

    for line_data in data.lines:
        line = QuotationTemplateLine(
            template_id=template.id,
            **line_data.model_dump(),
        )
        db.add(line)

    await db.commit()
    await db.refresh(template)
    return template
