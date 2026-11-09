"use client";

import { useMemo, useState } from "react";
import type { Job, LedgerEntry } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { locale, tx } from "@/lib/i18n";

const DAYS = 14;

export interface UsageDay {
  date: Date;
  minutes: number;
  credits: number;
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** 14 วันล่าสุด: นาทีจากคลิปที่พากย์เสร็จ และเครดิตที่ถูกตัด (หักรายการคืนแล้ว) */
export function usageDays(jobs: Job[], ledger: LedgerEntry[] | null, now = new Date()): UsageDay[] {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const days: UsageDay[] = [];
  const index = new Map<string, UsageDay>();
  for (let i = DAYS - 1; i >= 0; i--) {
    const date = new Date(start);
    date.setDate(start.getDate() - i);
    const row = { date, minutes: 0, credits: 0 };
    days.push(row);
    index.set(dayKey(date), row);
  }
  for (const job of jobs) {
    if (job.status !== "done" || !job.duration) continue;
    const row = index.get(dayKey(new Date(job.created_at)));
    if (row) row.minutes += job.duration / 60;
  }
  for (const entry of ledger ?? []) {
    if (entry.kind !== "charge" && entry.kind !== "refund") continue;
    const row = index.get(dayKey(new Date(entry.created_at * 1000)));
    if (!row) continue;
    const amount = Math.abs(entry.credits) + Math.abs(entry.minutes);
    row.credits += entry.kind === "refund" ? -amount : amount;
  }
  for (const row of days) row.credits = Math.max(0, row.credits);
  return days;
}

/** กราฟแท่งการใช้งาน 14 วัน สลับระหว่างนาทีที่พากย์กับเครดิตที่ถูกตัดได้ */
export default function UsageChart({ jobs, ledger, credits }: { jobs: Job[]; ledger: LedgerEntry[] | null; credits: boolean }) {
  const [mode, setMode] = useState<"minutes" | "credits">("minutes");
  const shown = credits && mode === "credits" ? "credits" : "minutes";
  const days = useMemo(() => usageDays(jobs, ledger), [jobs, ledger]);
  const values = days.map((d) => d[shown]);
  const max = Math.max(...values, 0);
  const total = values.reduce((sum, n) => sum + n, 0);
  const width = 560;
  const height = 150;
  const padX = 8;
  const padTop = 8;
  const padBottom = 22;
  const inner = height - padTop - padBottom;
  const slot = (width - padX * 2) / days.length;

  return (
    <section className="card dash-block" aria-labelledby="usage-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 id="usage-title">{tx("การใช้งาน")}</h2>
          <span className="muted" style={{ fontSize: 13 }}>
            {shown === "credits"
              ? tx("เครดิตที่ถูกตัดใน 14 วันที่ผ่านมา รวม {0}", { 0: fmtNum(total) })
              : tx("นาทีที่พากย์เสร็จใน 14 วันที่ผ่านมา รวม {0}", { 0: fmtNum(total) })}
          </span>
        </div>
        {credits && (
          <div className="seg small" role="group" aria-label={tx("หน่วยการใช้งาน")}>
            <button type="button" aria-pressed={shown === "minutes"} onClick={() => setMode("minutes")}>{tx("นาที")}</button>
            <button type="button" aria-pressed={shown === "credits"} onClick={() => setMode("credits")}>{tx("เครดิต")}</button>
          </div>
        )}
      </div>
      <svg className="usage-chart" viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label={shown === "credits"
          ? tx("กราฟเครดิตที่ใช้ 14 วัน รวม {0}", { 0: fmtNum(total) })
          : tx("กราฟนาทีที่พากย์ 14 วัน รวม {0}", { 0: fmtNum(total) })}>
        {days.map((day, i) => {
          const value = values[i];
          const h = max > 0 ? Math.max(value > 0 ? 3 : 0, (value / max) * inner) : 0;
          const x = padX + i * slot + (slot - Math.min(18, slot * 0.62)) / 2;
          const w = Math.min(18, slot * 0.62);
          const y = padTop + inner - h;
          const label = day.date.toLocaleDateString(locale(), { day: "numeric", month: "short" });
          const text = shown === "credits"
            ? tx("{0} เครดิต", { 0: fmtNum(value) })
            : tx("{0} นาที", { 0: fmtNum(value) });
          return (
            <g key={dayKey(day.date)}>
              <title>{label} · {text}</title>
              <rect x={x} y={value > 0 ? y : padTop + inner - 2} width={w} height={value > 0 ? h : 2} rx={4}
                className={value > 0 ? "on" : "off"} />
              {(i % 2 === 0 || i === days.length - 1) && (
                <text x={x + w / 2} y={height - 4} textAnchor="middle">{day.date.getDate()}</text>
              )}
            </g>
          );
        })}
      </svg>
      {total === 0 && <span className="dim">{tx("ยังไม่มีการใช้งานในช่วงนี้")}</span>}
    </section>
  );
}
