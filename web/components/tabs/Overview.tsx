"use client";

import { GitBranch } from "lucide-react";
import { fileUrl, kappa, type Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Bars, Card, Disclosure, Empty, Pill, RobBar, Stat, type Bar } from "../ui";

const CERTAINTY: Record<string, string> = { high: "good", moderate: "info", low: "warn", "very low": "crit" };

export function Overview({ run }: { run: Run }) {
  const { t, n, v } = useI18n();
  const { flow, agreement, studies, qa, themes } = run;
  if (!flow) return <Empty>{t("ov.empty")}</Empty>;

  const identified = flow.sources.reduce((sum, s) => sum + s.n, 0);
  const excludedReports = Object.values(flow.reports_excluded).reduce((a, b) => a + b, 0);
  const funnel: Bar[] = [
    { name: t("ov.f.identified"), value: identified, tip: flow.sources.map((s) => `${s.name} ${s.n}`).join(", ") },
    { name: t("ov.f.unique"), value: identified - flow.duplicates_removed, tip: t("ov.tip.duplicates", { n: flow.duplicates_removed }) },
    { name: t("ov.f.screened"), value: flow.records_screened, tip: t("ov.tip.cap", { n: flow.removed_by_automation }) },
    { name: t("ov.f.sought"), value: flow.reports_sought, tip: t("ov.tip.excluded", { n: flow.records_excluded }) },
    { name: t("ov.f.assessed"), value: flow.reports_assessed, tip: t("ov.tip.abstract", { n: flow.assessed_on_abstract_only }) },
    { name: t("ov.f.included"), value: flow.studies_included, key: true, tip: t("ov.tip.reasons", { n: excludedReports }) },
  ];

  const levels = studies.filter((s) => s.rob).map((s) => s.rob!.overall);
  const verified = studies.reduce((sum, s) => sum + s.quotes.verified, 0);
  const checked = studies.reduce((sum, s) => sum + s.quotes.checked, 0);
  const issues = qa?.issues.length ?? 0;
  const ta = agreement.title_abstract;

  return (
    <div className="stack">
      <div className="grid c4">
        <Stat label={t("ov.identified")} value={identified} note={n("database", flow.sources.length)} />
        <Stat label={t("ov.screened")} value={flow.records_screened} note={t("ov.byTwo")} />
        <Stat label={t("ov.included")} value={flow.studies_included} lead />
        <Stat label={t("ov.agreement")} value={kappa(ta)} unit="κ" note={v(ta?.interpretation)} />
      </div>

      <div className="grid c32">
        <Card title={t("ov.selection")} extra={t("ov.hover")}>
          <Bars rows={funnel} />
        </Card>
        <Card title={t("ov.glance")}>
          {!levels.length && !qa && <p className="muted">{t("ov.glanceEmpty")}</p>}
          {levels.length > 0 && (
            <div className="glance">
              <div className="glance-head">{t("ov.rob")}</div>
              <RobBar levels={levels} />
            </div>
          )}
          {checked > 0 && (
            <div className="glance">
              <div className="glance-head">
                {t("ov.quotes")}
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
                {t("ov.critic")}
                <Pill tone={issues ? "warn" : "good"}>{issues ? n("openIssue", issues) : t("ov.noIssue")}</Pill>
              </div>
            </div>
          )}
        </Card>
      </div>

      {themes.length > 0 && (
        <Card title={t("ov.themes")}>
          <div className="rows">
            {themes.map((theme) => (
              <div className="row" key={theme.name}>
                <span className="chip-id" title={t("ov.themeStudies")}>
                  {theme.studies}
                </span>
                <b style={{ fontWeight: 560 }}>{theme.name}</b>
                {theme.certainty && <Pill tone={CERTAINTY[theme.certainty] ?? ""}>{t("ov.certainty", { level: v(theme.certainty, true) })}</Pill>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {run.files.includes("prisma_flow.png") && (
        <Disclosure icon={<GitBranch size={16} />} title={t("ov.prisma")}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={fileUrl(run.id, "prisma_flow.png")} alt={t("ov.prisma")} style={{ display: "block", maxWidth: "100%", margin: "0 auto" }} />
        </Disclosure>
      )}
    </div>
  );
}
