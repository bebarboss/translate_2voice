import type { Job } from "@/lib/api";
import { STATUS_LABEL, stageLabel } from "@/lib/format";

import { tx } from "@/lib/i18n";
export default function StatusBadge({ job, detail = false }: { job: Job; detail?: boolean }) {
  let text = tx(STATUS_LABEL[job.status]);
  if (job.status === "queued" && job.queue_position) text = tx("รอคิว #{0}", { 0: job.queue_position });
  if (detail && job.status === "running") {
    text = job.stage === "cancelling"
      ? tx("กำลังยกเลิก")
      : `${stageLabel(job.stage)} ${Math.round(job.progress * 100)}%`;
  }
  return <span className={`badge ${job.status}`}>{text}</span>;
}
