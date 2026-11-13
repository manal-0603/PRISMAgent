import { ListChecks, Search, Workflow } from "lucide-react";
import type { Criterion, Run } from "@/lib/api";
import { Card, Disclosure, Empty } from "../ui";

function Criteria({ items }: { items: Criterion[] }) {
  return (
    <div className="rows">
      {items.map((c) => (
        <div className="row" key={c.id}>
          <span className="chip-id">{c.id}</span>
          <span>{c.text}</span>
          {c.full_text_only ? <span className="tag" title="Can only be judged on the full text">full text</span> : <span />}
        </div>
      ))}
    </div>
  );
}

export function ProtocolTab({ run }: { run: Run }) {
  const { protocol, strategy, briefs } = run;
  if (!protocol) return <Empty>The Planner agent has not written the protocol yet.</Empty>;
  const totalHits = strategy?.databases?.reduce((n, d) => n + (d.hits ?? 0), 0);

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
        <Card title="Include">
          <Criteria items={protocol.inclusion_criteria} />
        </Card>
        <Card title="Exclude">
          <Criteria items={protocol.exclusion_criteria} />
        </Card>
      </div>

      {strategy && (
        <Disclosure
          icon={<Search size={16} />}
          title="Search strategy"
          extra={`${strategy.databases?.length ?? 0} databases · ${totalHits?.toLocaleString("en-GB")} hits`}
        >
          {strategy.concepts.map((c, i) => (
            <div key={c.name} style={{ marginBottom: 14 }}>
              <div className="h5">
                Concept {i + 1} · {c.name}
              </div>
              <div className="badges">
                {c.free_text_terms.map((t) => (
                  <span className="tag" key={t}>
                    {t}
                  </span>
                ))}
                {c.controlled_terms.map((t) => (
                  <span className="pill info" key={t}>
                    {t}
                  </span>
                ))}
              </div>
            </div>
          ))}
          {strategy.databases?.map((d) => (
            <div key={d.key}>
              <div className="query-head">
                <b>{d.name}</b>
                <span className="muted num">{d.hits?.toLocaleString("en-GB") ?? "?"} hits</span>
              </div>
              <div className="query">{d.query}</div>
            </div>
          ))}
          <p className="hint" style={{ marginTop: 12 }}>
            The agent tested {strategy.refinement_log.length} queries on the live databases before settling on these.
          </p>
        </Disclosure>
      )}

      <Disclosure icon={<ListChecks size={16} />} title="Data to extract and planned methods" extra={`${protocol.data_items.length} data items`}>
        <div className="badges">
          {protocol.data_items.map((item) => (
            <span className="tag" key={item}>
              {item}
            </span>
          ))}
        </div>
        <div className="h5">Outcomes</div>
        <p>{protocol.outcomes.join("; ")}</p>
        <div className="h5">Study designs</div>
        <p>{protocol.study_designs.join(", ")}</p>
        <div className="h5">Risk of bias</div>
        <p>{protocol.risk_of_bias_approach}</p>
        <div className="h5">Synthesis</div>
        <p>{protocol.synthesis_plan}</p>
      </Disclosure>

      {briefs.length > 0 && (
        <Disclosure icon={<Workflow size={16} />} title="Briefs from the coordinator to the agents" extra={`${briefs.length} agents`}>
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
