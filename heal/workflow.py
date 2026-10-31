"""
The controlled self-healing loop for one incident:

  recall -> investigate (model) -> decide (guard) -> approve? -> remediate -> validate
                                       ^                                         |
                                       +----------- fix didn't work -------------+
  ... -> escalate (if denied/declined/still failing) -> learn (memory + audit)

Without --execute it is a dry run: it investigates and shows what the guard would allow,
but changes nothing and opens no tickets.
"""
from __future__ import annotations

from heal import actions, approval
from heal.agent import LLM, investigate
from heal.policy import RUNBOOK, guard
from heal.ports import Incident
from heal.tools import build_tools


def say(step: str, text: str) -> None:
    print(f"  [{step:<10}] {text}")


def handle(ctx, llm: LLM, inc: Incident, execute: bool) -> str:
    mem = ctx.memory
    print(f"\n{inc.key}\n  {inc.title}" + (f"\n  {inc.url}" if inc.url else ""))
    mem.audit(inc.key, "detect", source=inc.source, title=inc.title)

    past = mem.similar(inc.title)
    say("recall", f"{len(past)} similar past incident(s)" + (f", last: {past[0]['action']} -> {past[0]['outcome']}" if past else ""))

    say("investigate", "model is reading logs and state ...")
    rca = investigate(llm, inc, build_tools(ctx), mem.recent())
    action, params, sig = rca["proposed_action"], rca["params"], rca["signature"]
    mem.audit(inc.key, "analyze", **rca)
    say("analyze", f"[{rca['category']}] {rca['root_cause']}")
    say("propose", f"{action} {_p(params)}  (confidence {rca['confidence']})")

    outcome, reason, trail = "escalated", "", []
    while True:
        if action == "escalate":
            reason = "the model chose to escalate: " + rca["why"]
            break
        d = guard(action, params, ctx, inc.key, sig)
        mem.audit(inc.key, "decide", action=action, verdict=d.verdict, reason=d.reason)
        say("decide", f"{d.verdict.upper()}: {d.reason}")
        if d.verdict == "deny":
            reason = f"guard denied {action}: {d.reason}"
            break
        if d.verdict == "approval":
            if not execute:
                outcome, reason = "dry_run", f"would ask a human to approve {action}"
                break
            ok = approval.ask(f"{inc.key}: {action} {_p(params)} - {rca['root_cause']}")
            mem.audit(inc.key, "approval", approved=ok)
            if not ok:
                reason = f"human declined {action}"
                say("approve", "declined")
                break
            say("approve", "approved")
        if not execute:
            outcome, reason = "dry_run", f"would run {action} (pass --execute to act)"
            break
        result, state = actions.execute(action, params, ctx)
        mem.record_attempt(inc.key, action, result)
        mem.audit(inc.key, "remediate", action=action, result=result)
        say("remediate", result)
        ok, detail = actions.validate(action, params, state, ctx)
        mem.audit(inc.key, "validate", healthy=ok, detail=detail)
        say("validate", ("FIXED  " if ok else "STILL FAILING  ") + detail)
        trail.append(f"{action}: {result} -> {detail}")
        if ok:
            outcome = "resolved"
            if action == "argocd_rollback":
                _escalate(ctx, inc, rca, "Rolled back; git main still points at the bad commit. Revert or fix it before the "
                                         "next sync.", trail, follow_up=True)
            break
        # loop back to decide: the attempt limit now turns a second try into an escalation

    if outcome == "escalated":
        say("escalate", reason)
        if execute:
            say("escalate", _escalate(ctx, inc, rca, reason, trail))
        else:
            say("escalate", "dry run: no ticket opened")
            outcome = "dry_run"

    if execute:
        mem.add_history(sig, inc.source, action, outcome, inc.key)
        mem.mark_processed(inc.key, outcome)
    mem.audit(inc.key, "learn", outcome=outcome, signature=sig)
    say("learn", f"outcome {outcome.upper()}" + ("" if execute else " (dry run: memory not updated)"))
    return outcome


def _p(params: dict) -> str:
    return "(" + ", ".join(f"{k}={v}" for k, v in params.items() if v is not None) + ")"


def _escalate(ctx, inc: Incident, rca: dict, reason: str, trail: list[str], follow_up: bool = False) -> str:
    title = f"[heal-agent] {'follow-up: ' if follow_up else ''}{rca['signature']}"[:240]
    rb = RUNBOOK.get(rca["proposed_action"], {}).get("id", "-")
    body = "\n".join([
        f"**Incident** `{inc.key}` from **{inc.source}**: {inc.title}", inc.url and f"Link: {inc.url}", "",
        f"**Category:** {rca['category']}  |  **Confidence:** {rca['confidence']}  |  **Suggested owner:** {rca['owner']}",
        f"**Root cause:** {rca['root_cause']}", f"**Evidence:** {rca['evidence']}", "",
        f"**Agent proposal:** `{rca['proposed_action']}` ({rb}) {_p(rca['params'])} - {rca['why']}",
        f"**Why a human is needed:** {reason}", "",
        "**Actions taken:**", *(f"- {t}" for t in trail or ["none"]), "",
        "_Opened by the self-healing agent. Audit trail: runtime/audit.jsonl._"])
    if ctx.settings.escalation == "github_issue" and ctx.github:
        try:
            return ctx.github.open_issue(title, body, ["heal-agent"])
        except Exception as e:
            print(f"  ! could not open GitHub issue ({e}); printing instead")
    print("\n" + title + "\n" + body + "\n")
    return "escalation printed to stdout"
