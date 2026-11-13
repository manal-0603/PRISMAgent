import { GitBranch } from "lucide-react";
import { fileUrl, kappa, plural, type Run } from "@/lib/api";
import { Bars, Card, Disclosure, Empty, Pill, RobBar, Stat, type Bar } from "../ui";

const CERTAINTY: Record<string, string> = { high: "good", moderate: "info", low: "warn", "very low": "crit" };

export function Overview({ run }: { run: Run }) {
  const { flow, agreement, studies, qa, themes } = run;
  if (!flow) return <Empty>The overview fills in as soon as the first records are retrieved.</Empty>;

  const identified = flow.sources.reduce((sum, s) => sum + s.n, 0);
  const excludedReports = Object.values(flow.reports_excluded).reduce((a, b) => a + b, 0);
  const funnel: Bar[] = [
    { name: "Identified", value: identified, tip: flow.sources.map((s) => `${s.name} ${s.n}`).join(", ") },
    { name: "After de-duplication", value: identified - flow.duplicates_removed, tip: `${flow.duplicates_removed} duplicates merged` },
    { name: "Screened", value: flow.records_screened, tip: `${flow.removed_by_automation} records below the relevance cap were not screened` },
    { name: "Sought in full text", value: flow.reports_sought, tip: `${flow.records_excluded} records excluded on title and abstract` },
    { name: "Assessed", value: flow.reports_assessed, tip: `${flow.assessed_on_abstract_only} assessed on the abstract only` },
    { name: "Included", value: flow.studies_included, key: true, tip: `${excludedReports} reports excluded with reasons` },
  ];

  const levels = studies.filter((s) => s.rob).map((s) => s.rob!.overall);
  const verified = studies.reduce((n, s) => n + s.quotes.verified, 0);
  const checked = studies.reduce((n, s) => n + s.quotes.checked, 0);
  const issues = qa?.issues.length ?? 0;
  const ta = agreement.title_abstract;

  return (
    <div className="stack">
      <div className="grid c4">
        <Stat label="Records identified" value={identified} note={`${flow.sources.length} databases`} />
        <Stat label="Screened" value={flow.records_screened} note="by two reviewers" />
        <Stat label="Studies included" value={flow.studies_included} lead />
        <Stat label="Reviewer agreement" value={kappa(ta)} unit="κ" note={ta?.interpretation} />
      </div>

      <div className="grid c32">
        <Card title="Study selection" extra="hover a bar for details">
          <Bars rows={funnel} />
        </Card>
        <Card title="Quality at a glance">
          {!levels.length && !qa && <p className="muted">Available after extraction.</p>}
          {levels.length > 0 && (
            <div className="glance">
              <div className="glance-head">Risk of bias</div>
              <RobBar levels={levels} />
            </div>
          )}
          {checked > 0 && (
            <div className="glance">
              <div className="glance-head">
                Quotations found in the source
                <b className="num">{Math.round((verified / checked) * 100)}%</b>
              </div>
              <div className="meter">
                <span style={{ width: `${(verified / checked) * 100}%` }} />
              </div>
            </div>
          )}
          {qa && (
            <div className="glance">
              <div className="glance-head">
                Critic
                <Pill tone={issues ? "warn" : "good"}>{issues ? plural(issues, "open issue") : "No open issue"}</Pill>
              </div>
            </div>
          )}
        </Card>
      </div>

      {themes.length > 0 && (
        <Card title="Themes of the synthesis">
          <div className="rows">
            {themes.map((t) => (
              <div className="row" key={t.name}>
                <span className="chip-id" title="Studies in this theme">
                  {t.studies}
                </span>
                <b style={{ fontWeight: 560 }}>{t.name}</b>
                {t.certainty && <Pill tone={CERTAINTY[t.certainty] ?? ""}>Certainty: {t.certainty}</Pill>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {run.files.includes("prisma_flow.png") && (
        <Disclosure icon={<GitBranch size={16} />} title="PRISMA 2020 flow diagram">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={fileUrl(run.id, "prisma_flow.png")} alt="PRISMA 2020 flow diagram" style={{ display: "block", maxWidth: "100%", margin: "0 auto" }} />
        </Disclosure>
      )}
    </div>
  );
}
