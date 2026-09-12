"""Mechanics baseline: supplied specification v1.0, 2026-09-09."""
from decimal import Decimal
from datetime import datetime,timezone,timedelta

D = Decimal
REGION = 10000002
SYSTEM = 30000142
STATION = 60003760
COMPATIBILITY_DATE = '2026-09-09'

def compatibility_date():
    # ESI rejects dates later than its current calendar day in UTC-11.
    return min(COMPATIBILITY_DATE, datetime.now(timezone(timedelta(hours=-11))).date().isoformat())
SALES_TAX = D('0.075')
FACILITY_TAX = D('0.0025')
SCC = D('0.04')
ALPHA_SURCHARGE = D('0.0025')
SKILL_IDS = {'accounting': 16622, 'broker': 3446, 'advanced_broker': 16597,
             'industry': 3380, 'advanced_industry': 3388,
             'mass_production': 3387, 'advanced_mass_production': 24625}

def decimal(value):
    return D(str(value))

def tax(profile):
    return SALES_TAX * (1 - D('0.11') * int(profile.get('accounting', 0)))

def broker(profile):
    return max(D('0.01'), D('0.03') - D('0.003') * int(profile.get('broker', 0))
               - D('0.0003') * decimal(profile.get('faction', 0))
               - D('0.0002') * decimal(profile.get('corporation', 0)))

def relist_fee(old, new, profile):
    rate = broker(profile)
    discount = D('0.50') + D('0.06') * int(profile.get('advanced_broker', 0))
    return max(D(0), rate * (new - old)) + (1 - discount) * rate * new
