from tools import export_public_repository as public_export
from tools import check_public_repository as public_check


def test_continual_learning_and_gateway_sources_are_public_allowlisted() -> None:
    assert public_export._selected("docs/CONTINUAL_LEARNING_RETENTION.md")
    assert public_export._selected("gateway/pom.xml")
    assert public_export._selected(
        "gateway/src/main/java/io/visiondata/gate/gateway/FastApiProxyHandler.java"
    )


def test_gateway_runtime_and_build_outputs_remain_private() -> None:
    assert not public_export._selected("gateway/runtime/jre/bin/java.exe")
    assert not public_export._selected("gateway/target/visiondata-gateway.jar")


def test_public_checker_classifies_open_source_build_text_formats() -> None:
    assert {".cff", ".java", ".nsh"}.issubset(public_check.PUBLIC_TEXT_SUFFIXES)
