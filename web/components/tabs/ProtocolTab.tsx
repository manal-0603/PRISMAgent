"use client";

import { ListChecks, Search, Workflow } from "lucide-react";
import type { Criterion, Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Card, Disclosure, Empty } from "../ui";

function Criteria({ items }: { items: Criterion[] }) {
  const { t } = useI18n();
  return (
    <div className="rows">
      {items.map((c) => (
        <div className="row" key={c.id}>
          <span className="chip-id">{c.id}</span>
          <span>{c.text}</span>
          {c.full_text_only ? (
            <span className="tag" title={t("pr.fullTextTip")}>
              {t("pr.fullText")}
            </span>
          ) : (
            <span />
          )}
        </div>
      ))}
    </div>
  );
}

export function ProtocolTab({ run }: { run: Run }) {
  const { t, n, number } = useI18n();
  const { protocol, strategy, briefs } = run;
  if (!protocol) return <Empty>{t("pr.empty")}</Empty>;
  const totalHits = strategy?.databases?.reduce((sum, d) => sum + (d.hits ?? 0), 0) ?? 0;

  return (
    <div className="stack">
      <Card title={protocol.title} extra={protocol.framework}>
        <dl className="defs">
          {Object.entries(protocol.framework_elements).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <div className="grid c2">
        <Card title={t("pr.include")}>
          <Criteria items={protocol.inclusion_criteria} />
        </Card>
        <Card title={t("pr.exclude")}>
          <Criteria items={protocol.exclusion_criteria} />
        </Card>
      </div>

      {strategy && (
        <Disclosure
          icon={<Search size={16} />}
          title={t("pr.strategy")}
          extra={t("pr.strategyExtra", { dbs: n("database", strategy.databases?.length ?? 0), hits: number(totalHits) })}
        >
          {strategy.concepts.map((c, i) => (
            <div key={c.name} style={{ marginBottom: 14 }}>
              <div className="h5">
                {t("pr.concept", { i: i + 1 })} · {c.name}
              </div>
              <div className="badges">
                {c.free_text_terms.map((term) => (
                  <span className="tag" key={term}>
                    {term}
                  </span>
                ))}
                {c.controlled_terms.map((term) => (
                  <span className="pill info" key={term}>
                    {term}
                  </span>
                ))}
              </div>
            </div>
          ))}
          {strategy.databases?.map((d) => (
            <div key={d.key}>
              <div className="query-head">
                <b>{d.name}</b>
                <span className="muted num">{t("pr.hits", { n: d.hits !== null ? number(d.hits) : "?" })}</span>
              </div>
              <div className="query">{d.query}</div>
            </div>
          ))}
          <p className="hint" style={{ marginTop: 12 }}>
            {t("pr.tested", { n: strategy.refinement_log.length })}
          </p>
        </Disclosure>
      )}

      <Disclosure icon={<ListChecks size={16} />} title={t("pr.data")} extra={n("dataItem", protocol.data_items.length)}>
        <div className="badges">
          {protocol.data_items.map((item) => (
            <span className="tag" key={item}>
              {item}
            </span>
          ))}
        </div>
        <div className="h5">{t("pr.outcomes")}</div>
        <p>{protocol.outcomes.join("; ")}</p>
        <div className="h5">{t("pr.designs")}</div>
        <p>{protocol.study_designs.join(", ")}</p>
        <div className="h5">{t("ov.rob")}</div>
        <p>{protocol.risk_of_bias_approach}</p>
        <div className="h5">{t("pr.synthesis")}</div>
        <p>{protocol.synthesis_plan}</p>
      </Disclosure>

      {briefs.length > 0 && (
        <Disclosure icon={<Workflow size={16} />} title={t("pr.briefs")} extra={n("agent", briefs.length)}>
          {briefs.map((b) => (
            <div key={b.stage}>
              <div className="h5">{b.stage.replaceAll("_", " ")}</div>
              <p>{b.guidance}</p>
            </div>
          ))}
        </Disclosure>
      )}
    </div>
  );
}
