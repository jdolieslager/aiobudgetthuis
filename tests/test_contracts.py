"""Tests for contract discovery parsing (fixtures are fictional)."""

from aiobudgetthuis.models import Contract, relation_ids_from_contact_person

CONTACT_PERSON = {
    "contactPerson": {
        "contactPersonNumber": 1000001,
        "customers": [
            {
                "customerNumber": 2000002,
                "role": "Admin",
                "productCustomers": [
                    {
                        "productCustomerId": 3000003,
                        "productType": "Energy",
                        "hasActiveContracts": True,
                    }
                ],
            }
        ],
    }
}

PRODUCT_PICKER_CONTRACT = {
    "contractId": 4000004,
    "relationId": 3000003,
    "contractStatus": "Active",
    "contractType": "Dynamic",
    "supplyAddress": {
        "zipCode": "1234AB",
        "houseNumber": 1,
        "city": "VOORBEELDSTAD",
        "street": "VOORBEELDSTRAAT",
    },
    "connectionsInfo": [{"meterType": "SLM", "productType": "ELK"}],
}


def test_relation_ids_extracted():
    assert relation_ids_from_contact_person(CONTACT_PERSON) == [3000003]


def test_relation_ids_empty_when_absent():
    assert relation_ids_from_contact_person({}) == []
    assert relation_ids_from_contact_person({"contactPerson": {}}) == []


def test_contract_parsing_and_label():
    c = Contract.from_dict(PRODUCT_PICKER_CONTRACT)
    assert c.id == "4000004"
    assert c.type == "Dynamic"
    assert c.is_active is True
    assert c.label == "VOORBEELDSTRAAT 1, VOORBEELDSTAD - Dynamic"


def test_contract_inactive_and_missing_address():
    c = Contract.from_dict(
        {"contractId": 999, "contractStatus": "Ended", "contractType": "Fixed"}
    )
    assert c.id == "999"
    assert c.is_active is False
    assert c.label == "Fixed"  # no address -> falls back to type
