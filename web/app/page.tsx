"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { FileSearch, Plus } from "lucide-react";
import { fetcher, type RunSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useNewReview } from "@/components/Shell";

export default function Home() {
  const router = useRouter();
  const openNew = useNewReview();
  const { t } = useI18n();
  const { data: runs, error } = useSWR<RunSummary[]>("/api/runs", fetcher);

  // Open the review that needs attention first, otherwise the most recent finished one.
  useEffect(() => {
    if (!runs?.length) return;
    const pick = runs.find((r) => r.state === "running" || r.state === "waiting") ?? runs.find((r) => r.state === "finished") ?? runs[0];
    router.replace(`/runs/${pick.id}`);
  }, [runs, router]);

  if (error) {
    return (
      <div className="welcome">
        <h1>{t("home.apiDown")}</h1>
        <p>
          {t("home.apiHint")} <span className="mono">sysrev web</span>
        </p>
      </div>
    );
  }
  if (!runs || runs.length) return null;

  return (
    <div className="welcome">
      <div className="brand-mark" style={{ margin: "0 auto", width: 52, height: 52, borderRadius: 15 }}>
        <FileSearch size={26} />
      </div>
      <h1>{t("home.title")}</h1>
      <p>{t("home.text")}</p>
      <button className="btn primary" onClick={openNew}>
        <Plus size={16} /> {t("side.new")}
      </button>
    </div>
  );
}
