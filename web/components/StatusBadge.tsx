import type { Job } from "@/lib/api";
import { STATUS_LABEL, stageLabel } from "@/lib/format";

export default function StatusBadge({ job, detail = false }: { job: Job; detail?: boolean }) {
  let text = STATUS_LABEL[job.status];
  if (detail && job.status === "running") {
    text = job.stage === "cancelling"
      ? "กำลังยกเลิก"
      : `${stageLabel(job.stage)} ${Math.round(job.progress * 100)}%`;
  }
  return <span className={`badge ${job.status}`}>{text}</span>;
}
