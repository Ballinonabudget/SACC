"""Catalog enrichment requiring an exact SKU, with source attribution.

Catalog agreement verifies a SKU's product metadata, not the visual identity.
Never substitute resale prices for missing retail price/MSRP.
"""
import os
import re
from datetime import datetime, timezone

import requests


def normalize_sku(value):
    return re.sub(r'[\s-]', '', str(value or '')).upper()


def exact_product(payload, sku):
    rows = payload.get('data', [])
    rows = [rows] if isinstance(rows, dict) else rows
    if not isinstance(rows, list):
        return None
    matches = [row for row in rows if isinstance(row, dict)
               and normalize_sku(row.get('sku') or row.get('style_id')) == normalize_sku(sku)]
    # Multiple records can represent different releases or product variants.
    return matches[0] if len(matches) == 1 else None


def enrich_catalog(sku):
    key = os.getenv('KICKSDB_API_KEY', '')
    remote_enabled = (
        os.getenv('SACC_REMOTE_API_ENABLED', 'false').strip().lower()
        in {'1', 'true', 'yes', 'on'}
        and os.getenv('SACC_KICKSDB_API_ENABLED', 'false').strip().lower()
        in {'1', 'true', 'yes', 'on'}
    )
    result = {'status': 'api_locked' if not remote_enabled else ('missing_key' if not key else 'no_exact_match'),
              'name': None, 'release_date': None, 'msrp': None, 'currency': None,
              'sources': [], 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    if not remote_enabled or not key or not sku or sku.startswith('UNRESOLVED-'):
        return result
    for provider in ('stockx', 'goat'):
        url = f'https://api.kicks.dev/v3/{provider}/products'
        try:
            response = requests.get(url, params={'query': sku},
                                    headers={'Authorization': 'Bearer ' + key}, timeout=20)
            response.raise_for_status()
            product = exact_product(response.json(), sku)
            if not product:
                continue
            result['status'] = 'exact_sku_catalog_match'
            date = product.get('release_date') or None
            source = {'provider': 'kicksdb/' + provider, 'product_id': product.get('id'),
                      'sku': product.get('sku'), 'url': product.get('link'),
                      'release_date_raw': date}
            result['sources'].append(source)
            result['name'] = product.get('title') or product.get('name') or result['name']
            if date:
                result['release_date'] = date[:10]
            # Keep structured retail price with currency only when both are provided.
            price = product.get('retail_price') or product.get('retailPrice')
            currency = product.get('retail_currency') or product.get('currency')
            if isinstance(price, (int, float)) and price > 0 and currency:
                result['msrp'], result['currency'] = price, currency
        except (requests.RequestException, ValueError) as exc:
            result.setdefault('errors', []).append({'provider': provider, 'type': type(exc).__name__})
    return result
