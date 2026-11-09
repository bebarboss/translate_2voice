-- อ้างอิงผู้ให้บริการชำระเงิน (เช่น Stripe Checkout Session id)
alter table studio.topups add column if not exists provider_ref text;
