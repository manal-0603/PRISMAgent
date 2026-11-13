import { Check, LoaderCircle, User } from "lucide-react";
import type { Step } from "@/lib/api";

// Twelve stages: nine agent stages (round) and three human checkpoints (square).
export function Pipeline({ steps, running }: { steps: Step[]; running: boolean }) {
  return (
    <div className="pipeline" aria-label="Progress of the review">
      {steps.map((step) => {
        const human = step.kind === "human";
        return (
          <div key={step.key} className={`pstep ${step.state}${human ? " human" : ""}`} title={human ? `Human checkpoint: ${step.name}` : step.name}>
            <div className="pnode">
              {step.state === "done" ? (
                <Check size={14} strokeWidth={3} />
              ) : human ? (
                <User size={13} strokeWidth={2.4} />
              ) : step.state === "now" && running ? (
                <LoaderCircle size={14} className="spin" strokeWidth={2.6} />
              ) : null}
            </div>
            <div className="plabel">{human ? "You" : step.name}</div>
          </div>
        );
      })}
    </div>
  );
}
