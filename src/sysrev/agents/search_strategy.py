"""Search Strategy agent.

A tool-using agent: it drafts concept blocks (free-text synonyms + MeSH), writes one
query per database in that database's own syntax, then *tests* each query against
the live database with the `test_query` tool and refines it until the number of
hits is in a sensible window. Every tested query and its hit count is logged.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from ..context import RunContext
from ..models import Concept, Protocol, SearchStrategy
from ..sources.connectors import QUERY_SYNTAX, count_hits
from ..sources.http import SourceError
from .planner import ReviewPlan, protocol_brief

AGENT = "search_strategy"
MAX_TURNS = 9


class ConceptBlocks(BaseModel):
    concepts: list[Concept]


CONCEPT_SYSTEM = """You are an information specialist (medical librarian) designing the search \
of a systematic review. Break the review question into 2-4 concept blocks (the blocks will be \
combined with AND). For each block list the free-text terms to OR together: synonyms, spelling \
variants, abbreviations and related terms that authors really use in titles and abstracts (6-14 \
terms, most discriminating first). Add MeSH headings when the topic is biomedical, otherwise leave \
`controlled_terms` empty. Order the blocks from most to least essential. Prefer TWO blocks: do not \
create a block for outcomes, measures or study design — such words are often absent from abstracts and \
a block built on them silently loses relevant records."""

AGENT_SYSTEM = """You are an information specialist building the database searches of a \
systematic review. You have one tool, `test_query(database, query)`, which runs a query on the \
live database and returns the number of hits.

Your job, for EACH of these databases: {databases}
1. Write a query combining the first two concept blocks, in that database's syntax (below).
2. Test it with the tool.
3. Refine and test again until the hit count is between {low} and {high}:
   - too many hits: restrict terms to title/abstract fields, drop vague single words or broad \
headings, and only then AND a further concept block;
   - zero or very few hits: remove a block, add synonyms, or loosen phrases;
   - an ERROR means the syntax is wrong: fix it.
A sensitive search matters more than a precise one: when in doubt keep the broader query that fits \
the window. Date limit: {dates}

Test queries for several databases in the same turn. Stop after at most 3 refinements per database. \
The LAST query you tested successfully on a database is the one that will be executed, so finish \
each database on your preferred query. When every database is done, answer without a tool call: \
two or three plain sentences (no list, no table, no markdown, do not repeat the queries) explaining \
how the blocks were combined and what was traded off between sensitivity and precision.

Database syntax:
{syntax}

{guidance}"""


def fallback_query(database: str, concepts: list[Concept], protocol: Protocol) -> str:
    """Deterministic query builder, used when the agent leaves a database without a valid query."""
    # two most essential blocks; truncation (*) is only understood by PubMed
    strip = '"' if database == "pubmed" else '"*'
    blocks = [[t.translate({ord(ch): None for ch in strip}).strip() for t in c.free_text_terms[:10] if t.strip()] for c in concepts[:2]]
    blocks = [b for b in blocks if b]
    years = f"{protocol.date_from or ''}-{protocol.date_to or ''}" if (protocol.date_from or protocol.date_to) else ""

    def join(terms: list[str], fmt: str, sep: str) -> str:
        return "(" + sep.join(fmt.format(t=t) for t in terms) + ")"

    if database == "pubmed":
        query = " AND ".join(join(b, '"{t}"[tiab]', " OR ") for b in blocks)
        if years:
            query += f' AND ("{protocol.date_from or 1900}"[dp] : "{protocol.date_to or 3000}"[dp])'
        return query
    if database == "europepmc":
        query = " AND ".join(join(b, 'TITLE_ABS:"{t}"', " OR ") for b in blocks)
        if years:
            query += f" AND PUB_YEAR:[{protocol.date_from or 1900} TO {protocol.date_to or 3000}]"
        return query
    if database == "arxiv":
        return " AND ".join(join(b, 'abs:"{t}"', " OR ") for b in blocks)
    if database == "semantic_scholar":
        query = " + ".join(join(b, '"{t}"', " | ") for b in blocks)
        return f"{query} || {years}" if years else query
    query = " AND ".join(join(b, '"{t}"', " OR ") for b in blocks)  # openalex
    return f"{query} || {years}" if years else query


def design_strategy(ctx: RunContext, protocol: Protocol, plan: ReviewPlan | None = None) -> SearchStrategy:
    opts = ctx.options
    brief = protocol_brief(protocol)
    role = ctx.settings.role("search")
    blocks = ctx.llm.structured(role, CONCEPT_SYSTEM, brief, ConceptBlocks, agent=AGENT, max_tokens=1500)
    ctx.audit.log(AGENT, "concepts_defined", concepts=[c.name for c in blocks.concepts])

    low, high = 20, max(opts.max_per_source * 4, 400)
    history: dict[str, list[dict]] = {db: [] for db in protocol.databases}

    @tool
    def test_query(database: str, query: str) -> str:
        """Run `query` on a bibliographic `database` and return its number of hits."""
        if database not in history:
            return f"ERROR: unknown database '{database}'. Choose among: {', '.join(history)}."
        try:
            hits = count_hits(database, query, ctx.settings)
        except SourceError as exc:
            history[database].append({"query": query, "error": str(exc)})
            ctx.audit.log(AGENT, "query_tested", database=database, query=query, error=str(exc))
            return f"ERROR from {database}: {exc}. Check the syntax, or keep your last working query."
        history[database].append({"query": query, "hits": hits})
        ctx.audit.log(AGENT, "query_tested", database=database, query=query, hits=hits)
        verdict = "within the target window" if low <= hits <= high else ("too few" if hits < low else "too many")
        return f"{database}: {hits} hits ({verdict}; target {low}-{high})."

    system = AGENT_SYSTEM.format(
        databases=", ".join(protocol.databases),
        low=low,
        high=high,
        dates=(
            f"restrict to publication years {protocol.date_from or 'any'}-{protocol.date_to or 'present'} where the syntax allows it."
            if (protocol.date_from or protocol.date_to)
            else "the protocol sets NO date limit, so do not add one (ignore the years shown in the syntax examples)."
        ),
        syntax="\n".join(f"- {db}: {QUERY_SYNTAX[db]}" for db in protocol.databases),
        guidance=f"Coordinator guidance: {plan.guidance_for('search_strategy')}" if plan else "",
    )
    concept_text = "\n".join(
        f"- {c.name}: terms = {'; '.join(c.free_text_terms)}"
        + (f" | MeSH = {'; '.join(c.controlled_terms)}" if c.controlled_terms else "")
        for c in blocks.concepts
    )
    messages = [SystemMessage(system), HumanMessage(f"{brief}\n\nConcept blocks:\n{concept_text}")]
    model = ctx.llm.chat_model(role, max_tokens=1400).bind_tools([test_query])
    rationale = ""
    reminded = False
    for _ in range(MAX_TURNS):
        reply: AIMessage = ctx.llm.invoke(role, messages, agent=AGENT, model=model, max_tokens=1400)
        messages.append(reply)
        if not reply.tool_calls:
            untested = [db for db in protocol.databases if not any("hits" in h for h in history[db])]
            if untested and not reminded:  # the agent stopped early: send it back to work once
                reminded = True
                messages.append(HumanMessage(
                    f"You have not produced a working query for: {', '.join(untested)}. Test queries for them now."
                ))
                continue
            # keep prose only: the queries themselves are reported separately, verbatim
            prose = [line.strip() for line in str(reply.content).splitlines() if line.strip() and not line.strip().startswith(("|", "```", "#"))]
            rationale = " ".join(prose).replace("**", "").replace("`", "")[:700]
            break
        for call in reply.tool_calls:
            try:
                result = test_query.invoke(call["args"])
            except Exception as exc:  # noqa: BLE001 - malformed arguments from the model
                result = f"ERROR: invalid tool arguments ({exc}). Use test_query(database, query)."
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    queries, counts, log = {}, {}, []
    for db in protocol.databases:
        ok = [h for h in history[db] if "hits" in h]
        in_window = [h for h in ok if low <= h["hits"] <= high]
        non_empty = [h for h in ok if h["hits"] > 0]
        chosen = (in_window or non_empty or [None])[-1]
        for h in history[db]:
            log.append(f"{db}: {h.get('hits', h.get('error'))} hits <- {h['query']}")
        if chosen is None:
            query = fallback_query(db, blocks.concepts, protocol)
            try:
                hits = count_hits(db, query, ctx.settings)
            except SourceError as exc:
                hits = -1
                log.append(f"{db}: fallback query failed ({exc})")
            log.append(f"{db}: agent produced no valid query; deterministic fallback used ({hits} hits)")
            chosen = {"query": query, "hits": hits}
        queries[db], counts[db] = chosen["query"], chosen["hits"]

    strategy = SearchStrategy(
        concepts=blocks.concepts,
        queries=queries,
        rationale=rationale or "The agent reached its turn limit; the last successfully tested query per database was kept.",
        hit_counts=counts,
        refinement_log=log,
    )
    ctx.store.save("search_strategy", strategy, agent=AGENT)
    ctx.audit.log(AGENT, "strategy_finalised", hit_counts=counts)
    return strategy
