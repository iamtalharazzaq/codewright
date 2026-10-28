"""Explain (Phase 6 task 1): the code it finds for a question, in the 5 languages, and the diagram."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.chat import explain
from agent.chat.explain import FlowDiagram, FlowStep
from agent.tests.playbooks.helpers import llm_returning

GO_SERVICE = """package service

// InvoiceService bills customers.
type InvoiceService interface {
	Issue(ctx context.Context, id string) error
}

const Retries = 3

// Issue creates the invoice and mails it.
// It retries the mailer.
func (s *invoiceService) Issue(ctx context.Context, id string) error {
	inv, err := s.repo.Create(ctx, id)
	if err != nil {
		return err
	}

	return s.mailer.Send(inv)
}

func (s *invoiceService) Other() {}
"""

GO_HANDLER = """package http

func (h *Handler) Issue(c *gin.Context) {
	_ = h.svc.Issue(c, c.Param("id"))
}
"""

PY = '''"""Billing."""

MAX_LINES = 50


class Ledger:
    def post(self, amount):
        if amount < 0:
            raise ValueError("negative")
        self.total += amount

    def other(self):
        pass


def post_invoice(ledger, amount):
    ledger.post(amount)
'''

TS = """export interface Invoice {
  id: string;
}

export const formatTotal = (cents: number): string => {
  return (cents / 100).toFixed(2);
};

export async function sendInvoice(id: string): Promise<void> {
  await fetch(`/api/invoices/${id}`);
}
"""

CPP = """int add(int a, int b);

int add(int a, int b) {
  return a + b;
}

struct Point {
  int x;
};
"""


def project(tmp_path: Path) -> Path:
    files = {
        "internal/billing/service/invoice.go": GO_SERVICE,
        "internal/billing/port/http/handlers.go": GO_HANDLER,
        "internal/billing/service/mocks/InvoiceService.go": "func (m *Mock) Issue() error {\n\treturn nil\n}\n",
        "internal/billing/service/invoice_test.go": "func TestIssue(t *testing.T) {\n\tsvc.Issue()\n}\n",
        "app/ledger.py": PY,
        "web/invoice.ts": TS,
        "src/math.cpp": CPP,
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def test_find_symbols_takes_code_like_names_only() -> None:
    assert explain.find_symbols("How does PlaceOrder work?") == ["PlaceOrder"]
    assert explain.find_symbols("What do place_order() and Order.Pay do?") == ["place_order", "Order.Pay"]
    assert explain.find_symbols("What does MAX_RETRIES do?") == ["MAX_RETRIES"]
    assert explain.find_symbols("How does the payment module work?") == []


def test_plain_words_count_when_the_project_defines_them(tmp_path: Path) -> None:
    code = explain._code_files(project(tmp_path))
    assert explain.defined_names("How does Ledger work?", code) == ["Ledger"]
    assert explain.defined_names("How does `post_invoice` work?", code) == ["post_invoice"]
    assert explain.defined_names("How does Checkout work?", code) == []


def test_the_implementation_comes_first_with_its_doc_comment_and_ends_with_the_function(tmp_path: Path) -> None:
    found = explain.definitions(project(tmp_path), "Issue")
    assert [f.split(" in ", 1)[1].split(":", 1)[0] for f in found] == [
        "internal/billing/service/invoice.go",  # the implementation (not the interface line, mock or test)
        "internal/billing/port/http/handlers.go",  # then the entry point
    ]
    first = found[0]
    assert "// Issue creates the invoice and mails it." in first  # the comment above it
    assert "return s.mailer.Send(inv)" in first and "Other()" not in first  # cut at the function's end
    assert "    18  " not in first  # blank lines dropped, numbers kept: line 18 is empty


def test_definitions_in_every_language(tmp_path: Path) -> None:
    work = project(tmp_path)

    def source(name: str) -> str:
        return "\n".join(explain.definitions(work, name))

    assert "const Retries = 3" in source("Retries")
    assert "raise ValueError" in source("Ledger") and "def other" in source("Ledger")
    assert "MAX_LINES = 50" in source("MAX_LINES")
    assert "ledger.post(amount)" in source("post_invoice")
    assert "toFixed(2)" in source("formatTotal")
    assert "await fetch" in source("sendInvoice")
    assert "id: string;" in source("Invoice")
    cpp = source("add")
    assert "return a + b;" in cpp and "int add(int a, int b);" not in cpp  # the definition, not the declaration
    assert "int x;" in source("Point")


def test_definitions_share_one_budget(tmp_path: Path) -> None:
    work = project(tmp_path)
    (work / "big.go").write_text(
        "func Big() {\n" + "".join(f"\tx{i} := compute({i})\n" for i in range(120)) + "}\n", encoding="utf-8"
    )
    found = explain.definitions(work, "Big", budget=800)
    assert len("".join(found)) <= 800 and "... (cut)" in found[0]


def test_usages_skip_the_code_already_shown(tmp_path: Path) -> None:
    work = project(tmp_path)
    (work / "cmd/worker").mkdir(parents=True)
    (work / "cmd/worker/main.go").write_text(
        "package main\n\nfunc run() {\n\tsvc.Issue(ctx, next)\n}\n", encoding="utf-8"
    )
    code = explain._code_files(work)
    shown: set[tuple[str, int]] = set()
    explain.definitions(work, "Issue", files=code, shown=shown)
    used = explain.usages("Issue", code, shown)
    assert "cmd/worker/main.go L4: svc.Issue(ctx, next)" in used
    assert "service/invoice.go L12" not in used  # the definition line
    assert "handlers.go L4" not in used  # inside the handler's source, already shown
    assert "mocks" not in used and "_test.go" not in used


def test_a_module_question_gets_its_outline_and_the_code_behind_each_dependency(tmp_path: Path) -> None:
    work = project(tmp_path)
    (work / "internal/mailer").mkdir(parents=True)
    (work / "internal/mailer/mailer.go").write_text("package mailer\n\nfunc Send() {}\n", encoding="utf-8")
    (work / "internal/billing/service/wire.go").write_text(
        'package service\n\nimport "shop/internal/mailer"\n', encoding="utf-8"
    )
    graph: dict[str, Any] = {
        "nodes": [{"id": "internal/billing"}, {"id": "internal/mailer"}],
        "edges": [{"source": "internal/billing", "target": "internal/mailer", "weight": 3, "relations": {"calls": 3}}],
    }
    brief = explain.module_brief("internal/billing", graph, explain._code_files(work), 3000)
    assert "Module internal/billing defines:" in brief and "func (s *invoiceService) Issue" in brief
    assert "internal/billing depends on internal/mailer: calls 3" in brief
    assert 'internal/billing/service/wire.go L3: import "shop/internal/mailer"' in brief


def test_gather_says_when_nothing_matched(tmp_path: Path) -> None:
    found = explain.gather("How does Checkout work?", [], None, [], tmp_path)
    assert found.text == explain.NOTHING_FOUND and not found.has_code


def test_gather_finds_code_modules_and_files_within_the_budget(tmp_path: Path) -> None:
    work = project(tmp_path)
    found = explain.gather(
        "How does Issue work in billing?", ["internal/billing", "app"], lambda n: f"Node: {n}\nSource: x.go", [], work
    )
    assert found.has_code and found.modules == ["internal/billing"]
    assert found.files[0] == "internal/billing/service/invoice.go"
    assert "Graph facts for Issue" in found.text
    assert len(found.text) <= explain.SOURCE_CHARS + 200


def test_mermaid_from_steps_drops_steps_without_a_named_part() -> None:
    flow = FlowDiagram(
        kind="sequence",
        title="Issue",
        steps=[
            FlowStep(source="Client", target="billing service", action="POST /invoices"),
            FlowStep(source="", target="billing service", action="?"),
            FlowStep(source="billing service", target="mailer", action='send "invoice" -> customer'),
        ],
    )
    text = explain.to_mermaid(flow)
    assert text.splitlines()[:2] == ["sequenceDiagram", "    autonumber"]
    assert "participant billing_service as billing service" in text
    assert "billing_service->>mailer: send invoice to customer" in text  # quotes and arrows can't break Mermaid
    assert "?" not in text


async def test_no_diagram_when_no_step_names_a_part() -> None:
    client, _ = llm_returning(
        {"kind": "flowchart", "title": "x", "steps": [{"source": "", "target": "", "action": "a"}]}
    )
    assert await explain.diagram(client, "How?", "An explanation long enough to draw a diagram from. " * 3) is None
