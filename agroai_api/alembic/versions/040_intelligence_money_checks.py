"""Intelligence wallet money invariants enforced by PostgreSQL.

The commercial Intelligence API only debits a wallet under a row lock after
checking the balance, but a prepaid balance must never go negative even if a
future code path forgets that check. Ledger rows must also carry the sign their
kind implies: top-ups and refunds add value, charges remove it.

Constraints are created NOT VALID: PostgreSQL enforces them for every new
insert and update without re-scanning historical rows, so this revision can
never block a production release. SQLite (local/CI smoke databases) cannot add
CHECK constraints in place and is skipped; ORM models declare the same checks.

Revision ID: 040_intelligence_money_checks
Revises: 039_lifecycle_next_action
"""
from alembic import op

revision = "040_intelligence_money_checks"
down_revision = "039_lifecycle_next_action"
branch_labels = None
depends_on = None

WALLETS = "platform_intelligence_wallets"
LEDGER = "platform_intelligence_wallet_ledger"

CHECKS = (
    (WALLETS, "ck_intelligence_wallet_balance_nonnegative", "balance_cents >= 0"),
    (WALLETS, "ck_intelligence_wallet_funded_nonnegative", "lifetime_funded_cents >= 0"),
    (WALLETS, "ck_intelligence_wallet_spent_nonnegative", "lifetime_spent_cents >= 0"),
    (
        LEDGER,
        "ck_intelligence_wallet_ledger_amount_sign",
        "(kind = 'intelligence_charge' AND amount_cents < 0)"
        " OR (kind IN ('topup', 'intelligence_refund') AND amount_cents > 0)"
        " OR kind NOT IN ('intelligence_charge', 'topup', 'intelligence_refund')",
    ),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, name, expression in CHECKS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
                    ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, name, _expression in CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
