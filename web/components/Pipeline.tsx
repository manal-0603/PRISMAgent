"use client";

import { Check, LoaderCircle, User } from "lucide-react";
import type { Step } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// Twelve stages: nine agent stages (round) and three human checkpoints (square).
export function Pipeline({ steps, running }: { steps: Step[]; running: boolean }) {
  const { t } = useI18n();
  return (
    <div className="pipeline" aria-label={t("step.progress")}>
      {steps.map((step) => {
        const human = step.kind === "human";
        const name = t(`step.${step.key}` as Parameters<typeof t>[0]);
        return (
          <div key={step.key} className={`pstep ${step.state}${human ? " human" : ""}`} title={human ? t("step.humanTip", { name }) : name}>
            <div className="pnode">
              {step.state === "done" ? (
                <Check size={14} strokeWidth={3} />
              ) : human ? (
                <User size={13} strokeWidth={2.4} />
              ) : step.state === "now" && running ? (
                <LoaderCircle size={14} className="spin" strokeWidth={2.6} />
              ) : null}
            </div>
            <div className="plabel">{human ? t("step.you") : name}</div>
          </div>
        );
      })}
    </div>
  );
}
