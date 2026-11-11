"""PRISMA 2020 helpers: flow-diagram data, arithmetic validation, rendering, checklist."""

from __future__ import annotations

import textwrap
from pathlib import Path

from pydantic import BaseModel, Field


class PrismaFlow(BaseModel):
    identified: dict[str, int] = Field(default_factory=dict)  # per database
    duplicates_removed: int = 0
    removed_by_automation: int = 0  # date filter + relevance-ranking cap, applied before screening
    automation_detail: dict[str, int] = Field(default_factory=dict)  # reason -> n
    records_screened: int = 0
    records_excluded: int = 0
    reports_sought: int = 0
    reports_not_retrieved: int = 0  # excluded because no full text could be obtained
    reports_assessed: int = 0
    assessed_on_abstract_only: int = 0  # subset of reports_assessed (no open full text)
    reports_excluded: dict[str, int] = Field(default_factory=dict)  # reason -> n
    studies_included: int = 0

    @property
    def identified_total(self) -> int:
        return sum(self.identified.values())

    def check(self) -> list[str]:
        """Return the list of arithmetic inconsistencies (empty list = consistent)."""
        errors = []
        expected = self.identified_total - self.duplicates_removed - self.removed_by_automation
        if expected != self.records_screened:
            errors.append(
                f"identified ({self.identified_total}) - duplicates ({self.duplicates_removed}) - "
                f"automation ({self.removed_by_automation}) = {expected}, but records screened = {self.records_screened}"
            )
        if self.records_screened - self.records_excluded != self.reports_sought:
            errors.append(
                f"screened ({self.records_screened}) - excluded ({self.records_excluded}) != "
                f"reports sought ({self.reports_sought})"
            )
        if self.reports_sought - self.reports_not_retrieved != self.reports_assessed:
            errors.append(
                f"sought ({self.reports_sought}) - not retrieved ({self.reports_not_retrieved}) != "
                f"assessed ({self.reports_assessed})"
            )
        if self.reports_assessed - sum(self.reports_excluded.values()) != self.studies_included:
            errors.append(
                f"assessed ({self.reports_assessed}) - excluded ({sum(self.reports_excluded.values())}) != "
                f"included ({self.studies_included})"
            )
        return errors

    # -- rendering ---------------------------------------------------------- #
    def _boxes(self) -> dict[str, str]:
        from ..sources.connectors import DISPLAY_NAME

        per_db = "\n".join(f"{DISPLAY_NAME.get(name, name)}: n = {n}" for name, n in self.identified.items())
        # long criterion texts are shortened and wrapped so that they stay inside their box
        reasons = "\n".join(
            "\n".join(textwrap.wrap(f"{textwrap.shorten(reason, 110, placeholder='…')} (n = {n})", 50))
            for reason, n in self.reports_excluded.items()
        ) or "none"
        assessed = f"Reports assessed for eligibility\nn = {self.reports_assessed}"
        if self.assessed_on_abstract_only:
            assessed += f"\n(of which abstract only: n = {self.assessed_on_abstract_only})"
        return {
            "identified": f"Records identified from databases\nn = {self.identified_total}\n{per_db}",
            "removed": (
                "Records removed before screening\n"
                f"Duplicates: n = {self.duplicates_removed}\n"
                f"Marked ineligible by automation tools: n = {self.removed_by_automation}"
            ),
            "screened": f"Records screened\nn = {self.records_screened}",
            "excluded": f"Records excluded\nn = {self.records_excluded}",
            "sought": f"Reports sought for retrieval\nn = {self.reports_sought}",
            "not_retrieved": f"Reports not retrieved\nn = {self.reports_not_retrieved}",
            "assessed": assessed,
            "ft_excluded": f"Reports excluded, with reasons\nn = {sum(self.reports_excluded.values())}\n{reasons}",
            "included": f"Studies included in review\nn = {self.studies_included}",
        }

    def to_mermaid(self) -> str:
        b = {k: v.replace("\n", "<br/>").replace('"', "'") for k, v in self._boxes().items()}
        return "\n".join(
            [
                "flowchart TD",
                f'    A["{b["identified"]}"] --> B["{b["screened"]}"]',
                f'    A --> A2["{b["removed"]}"]',
                f'    B --> B2["{b["excluded"]}"]',
                f'    B --> C["{b["sought"]}"]',
                f'    C --> C2["{b["not_retrieved"]}"]',
                f'    C --> D["{b["assessed"]}"]',
                f'    D --> D2["{b["ft_excluded"]}"]',
                f'    D --> E["{b["included"]}"]',
            ]
        )

    def to_png(self, path: Path) -> Path:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch

        boxes = self._boxes()
        left = ["identified", "screened", "sought", "assessed", "included"]
        right = {"identified": "removed", "screened": "excluded", "sought": "not_retrieved", "assessed": "ft_excluded"}
        phases = ["Identification", "Screening", "Screening", "Screening", "Included"]

        def height(text: str) -> float:
            return 0.34 + 0.2 * (text.count("\n") + 1)

        row_h = [max(height(boxes[k]), height(boxes[right[k]]) if k in right else 0) for k in left]
        gap = 0.55
        total = sum(row_h) + gap * (len(left) - 1)
        fig, ax = plt.subplots(figsize=(11, total * 0.95 + 0.6), dpi=160)
        ax.set_xlim(0, 11)
        ax.set_ylim(-0.1, total + 0.15)
        ax.axis("off")

        def box(x: float, y_center: float, w: float, text: str, fill: str) -> None:
            h = height(text)
            ax.add_patch(
                FancyBboxPatch(
                    (x, y_center - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                    linewidth=1.1, edgecolor="#2f3b52", facecolor=fill,
                )
            )
            ax.text(x + w / 2, y_center, text, ha="center", va="center", fontsize=8.5, color="#111827")

        y = total
        centers = []
        for key, h in zip(left, row_h):
            centers.append(y - h / 2)
            y -= h + gap
        for i, key in enumerate(left):
            yc = centers[i]
            ax.text(0.25, yc, phases[i], rotation=90, ha="center", va="center", fontsize=8.5,
                    color="#2f3b52", fontweight="bold")
            box(0.7, yc, 4.4, boxes[key], "#eef2f8")
            if key in right:
                box(6.1, yc, 4.6, boxes[right[key]], "#fbf3e6")
                ax.annotate("", xy=(6.08, yc), xytext=(5.12, yc),
                            arrowprops=dict(arrowstyle="-|>", color="#2f3b52", lw=1.1))
            if i + 1 < len(left):
                ax.annotate(
                    "", xy=(2.9, centers[i + 1] + height(boxes[left[i + 1]]) / 2 + 0.02),
                    xytext=(2.9, yc - height(boxes[key]) / 2 - 0.02),
                    arrowprops=dict(arrowstyle="-|>", color="#2f3b52", lw=1.1),
                )
        ax.set_title("PRISMA 2020 flow diagram", fontsize=11, fontweight="bold", color="#111827")
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path


# --------------------------------------------------------------------------- #
# PRISMA 2020 checklist (27 items, 42 sub-items) mapped onto the manuscript the
# Writing agent produces. `sections` are the manuscript headings where the item
# is expected to be reported.
# --------------------------------------------------------------------------- #

PRISMA_2020_ITEMS: list[dict] = [
    {"id": "1", "topic": "Title", "sections": ["TITLE"]},
    {"id": "2", "topic": "Abstract", "sections": ["Abstract"]},
    {"id": "3", "topic": "Rationale", "sections": ["1.1 Rationale"]},
    {"id": "4", "topic": "Objectives", "sections": ["1.2 Objectives"]},
    {"id": "5", "topic": "Eligibility criteria", "sections": ["2.1 Eligibility criteria"]},
    {"id": "6", "topic": "Information sources", "sections": ["2.2 Information sources"]},
    {"id": "7", "topic": "Search strategy", "sections": ["2.3 Search strategy", "Appendix A"]},
    {"id": "8", "topic": "Selection process", "sections": ["2.4 Selection process"]},
    {"id": "9", "topic": "Data collection process", "sections": ["2.5 Data collection process"]},
    {"id": "10a", "topic": "Data items: outcomes", "sections": ["2.6 Data items"]},
    {"id": "10b", "topic": "Data items: other variables", "sections": ["2.6 Data items"]},
    {"id": "11", "topic": "Study risk of bias assessment", "sections": ["2.7 Risk of bias assessment"]},
    {"id": "12", "topic": "Effect measures", "sections": ["2.8 Effect measures"]},
    {"id": "13a", "topic": "Synthesis: eligibility for each synthesis", "sections": ["2.9 Synthesis methods"]},
    {"id": "13b", "topic": "Synthesis: data preparation", "sections": ["2.9 Synthesis methods"]},
    {"id": "13c", "topic": "Synthesis: tabulation and display", "sections": ["2.9 Synthesis methods"]},
    {"id": "13d", "topic": "Synthesis: methods and rationale", "sections": ["2.9 Synthesis methods"]},
    {"id": "13e", "topic": "Synthesis: heterogeneity exploration", "sections": ["2.9 Synthesis methods"]},
    {"id": "13f", "topic": "Synthesis: sensitivity analyses", "sections": ["2.9 Synthesis methods"]},
    {"id": "14", "topic": "Reporting bias assessment", "sections": ["2.10 Reporting bias and certainty assessment"]},
    {"id": "15", "topic": "Certainty assessment", "sections": ["2.10 Reporting bias and certainty assessment"]},
    {"id": "16a", "topic": "Study selection: flow", "sections": ["3.1 Study selection"]},
    {"id": "16b", "topic": "Study selection: excluded studies", "sections": ["3.1 Study selection", "Appendix B"]},
    {"id": "17", "topic": "Study characteristics", "sections": ["3.2 Study characteristics"]},
    {"id": "18", "topic": "Risk of bias in studies", "sections": ["3.3 Risk of bias in studies"]},
    {"id": "19", "topic": "Results of individual studies", "sections": ["3.4 Results of individual studies"]},
    {"id": "20a", "topic": "Syntheses: characteristics and risk of bias", "sections": ["3.5 Results of syntheses"]},
    {"id": "20b", "topic": "Syntheses: statistical results", "sections": ["3.5 Results of syntheses"]},
    {"id": "20c", "topic": "Syntheses: heterogeneity", "sections": ["3.5 Results of syntheses"]},
    {"id": "20d", "topic": "Syntheses: sensitivity analyses", "sections": ["3.5 Results of syntheses"]},
    {"id": "21", "topic": "Reporting biases", "sections": ["3.6 Reporting biases and certainty of evidence"]},
    {"id": "22", "topic": "Certainty of evidence", "sections": ["3.6 Reporting biases and certainty of evidence"]},
    {"id": "23a", "topic": "Discussion: interpretation", "sections": ["4.1 Summary of evidence"]},
    {"id": "23b", "topic": "Discussion: limitations of the evidence", "sections": ["4.2 Limitations of the evidence"]},
    {"id": "23c", "topic": "Discussion: limitations of the review process", "sections": ["4.3 Limitations of the review process"]},
    {"id": "23d", "topic": "Discussion: implications", "sections": ["4.4 Implications"]},
    {"id": "24a", "topic": "Registration", "sections": ["5.1 Registration and protocol"]},
    {"id": "24b", "topic": "Protocol access", "sections": ["5.1 Registration and protocol"]},
    {"id": "24c", "topic": "Protocol amendments", "sections": ["5.1 Registration and protocol"]},
    {"id": "25", "topic": "Support", "sections": ["5.2 Support"]},
    {"id": "26", "topic": "Competing interests", "sections": ["5.3 Competing interests"]},
    {"id": "27", "topic": "Availability of data, code and other materials", "sections": ["5.4 Availability of data, code and other materials"]},
]


def split_sections(markdown: str) -> dict[str, str]:
    """Map every heading of a Markdown manuscript to the text below it."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in markdown.splitlines():
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            heading = line.lstrip("#").strip()
            current = "TITLE" if level == 1 and "TITLE" not in sections else heading
            sections[current] = [heading] if current == "TITLE" else []
        elif current:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def validate_checklist(markdown: str, min_words: int = 6) -> list[dict]:
    """Rule-based PRISMA 2020 validator.

    An item counts as *reported* when one of its expected sections exists and holds
    at least `min_words` words (the title only needs to name the review type).
    This checks completeness of reporting, not the quality of what is reported —
    that judgement is left to the Critic agent and to the human reviewer.
    """
    sections = split_sections(markdown)

    def find(prefix: str) -> tuple[str, str] | None:
        for heading, body in sections.items():
            if heading.lower().startswith(prefix.lower()):
                return heading, body
        return None

    rows = []
    for item in PRISMA_2020_ITEMS:
        found, where = False, ""
        for target in item["sections"]:
            hit = find(target)
            if not hit:
                continue
            heading, body = hit
            if item["id"] == "1":
                found = "systematic review" in body.lower()
            else:
                found = len(body.split()) >= min_words
            if found:
                where = heading
                break
        rows.append({"item": item["id"], "topic": item["topic"], "reported": found, "location": where})
    return rows


def checklist_markdown(rows: list[dict]) -> str:
    lines = ["| Item | Topic | Reported | Location in manuscript |", "|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| {row['item']} | {row['topic']} | {'Yes' if row['reported'] else 'No'} | {row['location'] or '-'} |"
        )
    return "\n".join(lines)
