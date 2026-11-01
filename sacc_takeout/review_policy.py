"""Reversible local review policies over immutable recovery observations."""
from copy import deepcopy

REVIEW_POLICY_VERSION = 'screenshot-gps-v1'


def valid_screenshot_review(payload):
    return (isinstance(payload, dict) and payload.get('context_type') == 'screenshot_review'
            and type(payload.get('is_screenshot')) is bool
            and all(isinstance(payload.get(k), str) and payload[k].strip() for k in ('reviewer', 'evidence')))


def reviewed_result(result, media_type, decisions):
    """Decisions must be in latest-insertion-first order. Never change input."""
    value = deepcopy(result)
    decision = next((d for d in decisions if valid_screenshot_review(d.get('payload'))), None)
    screenshot = bool(media_type == 'image' and decision and decision['payload']['is_screenshot'])
    value['media_subtype'] = 'screenshot' if screenshot else 'unspecified'
    value['gps_requirement'] = {'status': 'not_expected_screenshot' if screenshot else 'expected',
                                'decision_id': decision['id'] if decision else None,
                                'policy_version': REVIEW_POLICY_VERSION}
    if screenshot:
        value['review_reasons'] = [r for r in value.get('review_reasons', []) if r != 'gps_missing']
    return value
