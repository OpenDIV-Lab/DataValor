"""Offline connector tests for E3 (no DataHub/OpenMetadata/Spark required)."""

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_gov import CatalogQuery, FieldSchema, MetadataRecord
from datavalor.data_gov.backends.datahub import DataHubMetadataCatalog
from datavalor.data_gov.backends.deequ import DeequPolicyEvaluator, DeequValidationAdapter
from datavalor.data_gov.backends.openmetadata import OpenMetadataCatalog


def record():
    return MetadataRecord("p1", (FieldSchema("age", "INT", nullable=True),), "owner", "warehouse",
                          properties={"description": "demo"})


def product():
    return DataProduct("p1", "demo", DataReference("memory://p1", "records"), "owner")


def test_datahub_emitter_and_client_are_mapped_without_importing_sdk():
    class Emitter:
        def emit_mcp(self, event):
            self.event = event

    class Client:
        def get(self, product_id):
            return {"product_id": product_id, "fields": [{"name": "age", "type": "INT"}], "owner": "owner"}

        def search(self, text, limit=100):
            return [{"product_id": "p1", "fields": []}]

    emitter = Emitter()
    catalog = DataHubMetadataCatalog(emitter=emitter, client=Client(), event_builder=lambda r: {"id": r.product_id})
    saved = catalog.upsert(record(), RunContext("e3"))
    assert emitter.event == {"id": "p1"}
    assert saved.properties["connector"] == "datahub"
    assert catalog.get("p1", RunContext("e3")).fields[0].name == "age"
    assert catalog.search(CatalogQuery(text="demo"), RunContext("e3"))[0].product_id == "p1"


def test_openmetadata_client_mapping_and_retry_boundary():
    class Client:
        def __init__(self):
            self.calls = 0

        def create_or_update(self, entity):
            self.calls += 1
            return entity

        def get_by_name(self, name):
            return {"name": name, "schemaDefinition": {"columns": [{"name": "x", "dataType": "STRING"}]}}

        def search(self, text):
            return [{"name": "p1"}]

    client = Client()
    catalog = OpenMetadataCatalog(client=client, retries=1)
    assert catalog.upsert(record(), RunContext("e3")).properties["connector"] == "openmetadata"
    assert client.calls == 1
    assert catalog.get("p1", RunContext("e3")).product_id == "p1"
    assert len(catalog.search(CatalogQuery(text="p"), RunContext("e3"))) == 1


def test_deequ_result_becomes_artifact_and_governance_findings():
    def runner(**kwargs):
        return {"checks": [
            {"status": "Success", "constraint": "isComplete"},
            {"status": "Failure", "constraint": "isUnique", "message": "duplicate values"},
        ]}
    artifact = DeequValidationAdapter(runner=runner).validate(product(), (), RunContext("e3"))
    assert artifact.kind == "governance.deequ_validation"
    report = DeequPolicyEvaluator(runner=runner).evaluate(product(), "publish", None, RunContext("e3"))
    assert report.decision.value == "review"
    assert report.findings[0].code == "deequ.constraint_failed"
