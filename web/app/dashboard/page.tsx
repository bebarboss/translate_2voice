"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PlusIcon } from "@/components/Icons";
import StatusBadge from "@/components/StatusBadge";
import UsageChart from "@/components/UsageChart";
import { api, type ActorMe, type Job, type PaymentOrder, type Project, type UsageSummary, type Wallet } from "@/lib/api";
import { TARGET_LABEL, fmtBaht, fmtDuration, fmtNum, fmtWhen, isActive, langName } from "@/lib/format";
import { locale, tx } from "@/lib/i18n";
import { useAuth } from "@/lib/useAuth";

const ATTENTION = new Set(["awaiting_review", "failed", "queued", "running"]);
type DashMode = "work" | "earn" | "payout";

/** เดือนตามเวลาไทย ตรงกับที่ API ตัดรอบค่าตอบแทนนักพากย์ */
function thaiMonth(now = Date.now()): string {
  return new Date(now + 7 * 3600_000).toISOString().slice(0, 7);
}

const fmtMin = (sec: number) => tx("{0} นาที", { 0: (sec / 60).toLocaleString(locale(), { maximumFractionDigits: 1 }) });
const fmtMonth = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(locale(), { month: "short", year: "numeric" });

function attentionRank(job: Job): number {
  if (job.status === "awaiting_review") return 0;
  if (job.status === "failed") return 1;
  if (job.status === "running") return 2;
  return 3;
}

/** ภาพรวมของผู้ใช้: งานที่ต้องดูแล งานล่าสุด โปรเจกต์ และเครดิต */
export default function DashboardPage() {
  const { config, user, loaded } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [slips, setSlips] = useState<PaymentOrder[]>([]);
  const [actorMe, setActorMe] = useState<ActorMe | null>(null);
  const [payoutRows, setPayoutRows] = useState<UsageSummary[] | null>(null);
  const [mode, setMode] = useState<DashMode>("work");
  const [error, setError] = useState("");

  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/dashboard";
  }, [loaded, config, user]);

  useEffect(() => {
    if (!loaded || (config?.auth && !user)) return;
    let stop = false;
    const load = () => {
      api.listJobs().then((list) => { if (!stop) { setJobs(list); setError(""); } })
        .catch((e) => { if (!stop) { setError(e.message); setJobs((prev) => prev ?? []); } });
      api.listProjects().then((list) => { if (!stop) setProjects(list); }).catch(() => { if (!stop) setProjects([]); });
      if (config?.billing && user && !user.admin) api.wallet().then((w) => { if (!stop) setWallet(w); }).catch(() => {});
      if (config?.payment_provider === "slip" && user) {
        api.myPayments().then((list) => {
          if (!stop) setSlips(list.filter((o) => o.status === "pending" || o.status === "review" || o.status === "rejected"));
        }).catch(() => {});
      }
    };
    load();
    const timer = setInterval(load, 8000);
    return () => { stop = true; clearInterval(timer); };
  }, [loaded, config, user]);

  useEffect(() => {
    if (!user) return;
    let stop = false;
    const load = () => {
      api.actorMe().then((me) => { if (!stop) setActorMe(me); }).catch(() => {});
      if (user.admin) {
        api.adminActorUsage(thaiMonth()).then((data) => {
          if (!stop) setPayoutRows(data.rows);
        }).catch(() => {});
      }
    };
    load();
    const timer = setInterval(load, 60000);
    return () => { stop = true; clearInterval(timer); };
  }, [user]);

  if (!loaded || (config?.auth && !user)) return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;

  const list = jobs ?? [];
  const attention = list.filter((j) => ATTENTION.has(j.status)).sort((a, b) => attentionRank(a) - attentionRank(b)).slice(0, 6);
  const attentionIds = new Set(attention.map((j) => j.id));
  const recent = list.filter((j) => !attentionIds.has(j.id)).slice(0, 5);
  const review = list.filter((j) => j.status === "awaiting_review").length;
  const active = list.filter((j) => isActive(j)).length;
  const done = list.filter((j) => j.status === "done");
  const dubbed = done.reduce((sum, j) => sum + (j.duration ?? 0), 0);
  const credits = wallet ? wallet.credits + (wallet.subscription?.minutes_left ?? 0) : null;
  const name = user?.name?.trim();
  const actor = actorMe?.actor ?? null;
  const actorOn = actor?.status === "approved";
  const usage = actorOn ? actorMe?.usage ?? [] : [];
  const due = usage.reduce((sum, row) => sum + Math.max(0, row.due), 0);
  const monthUsage = usage.find((row) => row.month === thaiMonth());
  const actorNotes = [
    actor?.status === "pending" ? { key: "apply", title: tx("ส่งใบสมัครแล้ว"), detail: tx("รอผู้ดูแลอนุมัติใบสมัคร") } : null,
    actor?.status === "rejected" ? { key: "rejected", title: tx("ใบสมัครไม่ผ่าน"), detail: actor.note || tx("แก้ไขแล้วสมัครใหม่ได้") } : null,
    actorOn && actorMe && !actorMe.consent_current ? { key: "consent", title: tx("นักพากย์"), detail: tx("หนังสือยินยอมมีเวอร์ชันใหม่") } : null,
    actorOn && actorMe && !actorMe.payment && due > 0
      ? { key: "pay", title: tx("ค่าตอบแทน"), detail: tx("กรอกข้อมูลรับเงินก่อน ผู้ดูแลถึงจะจ่ายค่าตอบแทนให้ได้") } : null,
  ].filter((item): item is { key: string; title: string; detail: string } => item !== null);
  const payoutDue = payoutRows ? payoutRows.reduce((sum, row) => sum + Math.max(0, row.due), 0) : null;
  const modes: { id: DashMode; label: string; flag: boolean }[] = [{ id: "work", label: tx("งาน"), flag: false }];
  if (actor) modes.push({ id: "earn", label: tx("ค่าตอบแทน"), flag: due > 0 || actor.status === "pending" });
  if (user?.admin) modes.push({ id: "payout", label: tx("จ่ายนักพากย์"), flag: (payoutDue ?? 0) > 0 });
  const shown = modes.some((item) => item.id === mode) ? mode : "work";
  const payoutList = [...(payoutRows ?? [])].sort((a, b) => Math.max(0, b.due) - Math.max(0, a.due));

  return (
    <main className="page" style={{ maxWidth: 1080 }}>
      <div className="page-head">
        <div>
          <h1>{name ? tx("สวัสดี {0}", { 0: name }) : tx("ภาพรวม")}</h1>
          <span className="muted">
            {shown === "earn" ? (actor?.stage_name ? `${actor.stage_name} · ${tx("ค่าตอบแทนของฉัน")}` : tx("ค่าตอบแทนของฉัน"))
              : shown === "payout" ? tx("ค้างจ่ายนักพากย์เดือนนี้")
                : review > 0 ? tx("{0} งานรอตรวจบท", { 0: review })
                  : active > 0 ? tx("{0} งานกำลังทำ", { 0: active })
                    : tx("ส่งคลิปใหม่ หรือเปิดงานที่ทำค้างไว้")}
          </span>
        </div>
        {shown === "earn" ? <Link href="/actor" className="btn primary">{tx("เปิดหน้านักพากย์")}</Link>
          : shown === "payout" ? <Link href="/actors" className="btn primary">{tx("ตรวจนักพากย์")}</Link>
            : <Link href="/" className="btn primary"><PlusIcon />{tx("ส่งคลิปใหม่")}</Link>}
      </div>

      {modes.length > 1 && (
        <div className="dash-modes">
          <div className="seg" role="tablist" aria-label={tx("โหมดภาพรวม")}>
            {modes.map((item) => (
              <button key={item.id} type="button" role="tab" aria-selected={shown === item.id} aria-pressed={shown === item.id}
                onClick={() => setMode(item.id)}>
                {item.label}
                {item.flag && <span className="dot" aria-hidden="true" />}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && <div className="alert error" role="alert">{error}</div>}

      {shown === "work" && (
      <section className="dash-stats" aria-label={tx("สรุปงาน")}>
        <Link href="/jobs" className="card dash-stat">
          <b>{jobs ? list.length : "…"}</b>
          <span>{tx("งานทั้งหมด")}</span>
        </Link>
        <Link href="/jobs" className={`card dash-stat${review ? " hot" : ""}`}>
          <b>{jobs ? review : "…"}</b>
          <span>{tx("รอตรวจบท")}</span>
        </Link>
        <Link href="/jobs" className="card dash-stat">
          <b>{jobs ? active : "…"}</b>
          <span>{tx("กำลังทำ")}</span>
        </Link>
        <Link href="/jobs" className="card dash-stat">
          <b>{jobs ? done.length : "…"}</b>
          <span>{tx("เสร็จแล้ว")}{dubbed > 0 ? ` · ${tx("รวม {0}", { 0: fmtDuration(dubbed) })}` : ""}</span>
        </Link>
        {config?.billing && user && (
          <Link href={user.admin ? "/account" : "/promotions"} className="card dash-stat">
            <b>{user.admin ? tx("ไม่จำกัด") : credits == null ? "…" : fmtNum(credits)}</b>
            <span>{user.admin ? tx("บัญชีผู้ดูแล") : tx("เครดิตคงเหลือ")}</span>
          </Link>
        )}
      </section>
      )}

      {shown === "work" && jobs && (
        <UsageChart jobs={list} ledger={wallet?.ledger ?? null} credits={!!config?.billing && !!user && !user.admin} />
      )}

      {shown === "work" && (attention.length > 0 || slips.length > 0) && (
        <section className="card dash-block" aria-labelledby="attention-title">
          <h2 id="attention-title">{tx("ต้องดูแล")}</h2>
          {slips.map((o) => (
            <Link key={o.id} href="/promotions" className="dash-row">
              <span className="sq" aria-hidden="true">฿</span>
              <span className="dash-main">
                <b>{tx("สลิป {0}", { 0: fmtBaht(o.amount) })}</b>
                <span>{o.note || tx(o.status === "pending" ? "รอโอน" : o.status === "rejected" ? "สลิปไม่ผ่าน" : "รอตรวจสลิป")}</span>
              </span>
            </Link>
          ))}
          {attention.map((j) => (
            <Link key={j.id} href={`/jobs/${j.id}`} className="dash-row">
              <span className="sq" aria-hidden="true">{j.filename.slice(0, 1).toUpperCase()}</span>
              <span className="dash-main">
                <b title={j.filename}>{j.filename}</b>
                <span>{langName(j.detected_lang ?? j.source_lang)} → {tx(TARGET_LABEL[j.target_lang])} · {fmtWhen(j.updated_at)}</span>
              </span>
              <StatusBadge job={j} detail />
            </Link>
          ))}
        </section>
      )}

      {shown === "earn" && (
        <>
          {actorOn && (
            <section className="dash-stats" aria-label={tx("ค่าตอบแทนของฉัน")}>
              <Link href="/actor" className={`card dash-stat${due > 0 ? " hot" : ""}`}>
                <b>{fmtBaht(due)}</b>
                <span>{tx("ค่าตอบแทนค้างจ่าย")}</span>
              </Link>
              <Link href="/actor" className="card dash-stat">
                <b>{fmtBaht(monthUsage?.amount ?? 0)}</b>
                <span>{tx("ค่าตอบแทนเดือนนี้")}</span>
              </Link>
              <Link href="/actor" className="card dash-stat">
                <b>{fmtMin(monthUsage?.seconds ?? 0)}</b>
                <span>{tx("เวลาที่ใช้")}</span>
              </Link>
              <Link href="/actor" className="card dash-stat">
                <b>{fmtBaht(monthUsage?.paid ?? 0)}</b>
                <span>{tx("จ่ายแล้ว")}</span>
              </Link>
            </section>
          )}
          {actorNotes.length > 0 && (
            <section className="card dash-block" aria-label={tx("ต้องดูแล")}>
              {actorNotes.map((item) => (
                <Link key={item.key} href={item.key === "pay" ? "/account#payout" : "/actor"} className="dash-row">
                  <span className="sq" aria-hidden="true">฿</span>
                  <span className="dash-main">
                    <b>{item.title}</b>
                    <span>{item.detail}</span>
                  </span>
                </Link>
              ))}
            </section>
          )}
          {actorOn && (
            <section className="card dash-block" aria-labelledby="earn-title">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 id="earn-title">{tx("ค่าตอบแทน")}</h2>
                <Link href="/actor" className="btn small">{tx("ทั้งหมด")}</Link>
              </div>
              {usage.length === 0 ? <div className="empty">{tx("ยังไม่มีการใช้เสียง")}</div>
                : usage.map((row) => (
                  <Link key={row.month} href="/actor" className="dash-row">
                    <span className="dash-main">
                      <b>{fmtMonth(row.month)}</b>
                      <span>{fmtMin(row.seconds)} · {tx("จ่ายแล้ว")} {fmtBaht(row.paid)} · {tx("ค้างจ่าย")} {fmtBaht(Math.max(0, row.due))}</span>
                    </span>
                  </Link>
                ))}
            </section>
          )}
        </>
      )}

      {shown === "payout" && (
        <>
          <section className="dash-stats" aria-label={tx("จ่ายนักพากย์")}>
            <Link href="/actors" className={`card dash-stat${payoutDue ? " hot" : ""}`}>
              <b>{payoutDue == null ? "…" : fmtBaht(payoutDue)}</b>
              <span>{tx("ค้างจ่ายนักพากย์เดือนนี้")}</span>
            </Link>
          </section>
          <section className="card dash-block" aria-labelledby="payout-title">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 id="payout-title">{fmtMonth(thaiMonth())}</h2>
              <Link href="/actors" className="btn small">{tx("ทั้งหมด")}</Link>
            </div>
            {payoutRows === null ? <div className="empty">{tx("กำลังโหลด...")}</div>
              : payoutList.length === 0 ? <div className="empty">{tx("เดือนนี้ยังไม่มีการใช้เสียงนักพากย์")}</div>
                : payoutList.map((row) => (
                  <Link key={row.actor_id} href="/actors" className="dash-row">
                    <span className="dash-main">
                      <b>{row.stage_name}</b>
                      <span>
                        {fmtMin(row.seconds)} · {tx("จ่ายแล้ว")} {fmtBaht(row.paid)} · {tx("ค้างจ่าย")} {fmtBaht(Math.max(0, row.due))}
                        {!row.payee && row.due > 0 ? ` · ${tx("ยังไม่ได้กรอกบัญชีรับเงิน")}` : ""}
                      </span>
                    </span>
                  </Link>
                ))}
          </section>
        </>
      )}

      {shown === "work" && <div className="dash-split">
        <section className="card dash-block" aria-labelledby="recent-title">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 id="recent-title">{tx("งานล่าสุด")}</h2>
            <Link href="/jobs" className="btn small">{tx("ดูงานทั้งหมด")}</Link>
          </div>
          {jobs === null ? <div className="empty">{tx("กำลังโหลด...")}</div>
            : recent.length === 0 && attention.length === 0 ? (
              <div className="empty">
                {tx("ยังไม่มีงาน")}
                <div><Link href="/" className="btn primary small">{tx("ส่งคลิปใหม่")}</Link></div>
              </div>
            ) : recent.length === 0 ? <div className="empty">{tx("งานที่เหลืออยู่ในรายการด้านบน")}</div>
              : recent.map((j) => (
                <Link key={j.id} href={`/jobs/${j.id}`} className="dash-row">
                  <span className="sq" aria-hidden="true">{j.filename.slice(0, 1).toUpperCase()}</span>
                  <span className="dash-main">
                    <b title={j.filename}>{j.filename}</b>
                    <span>{langName(j.detected_lang ?? j.source_lang)} → {tx(TARGET_LABEL[j.target_lang])} · {fmtWhen(j.updated_at)}</span>
                  </span>
                  <StatusBadge job={j} />
                </Link>
              ))}
        </section>

        <div className="dash-side">
          <section className="card dash-block" aria-labelledby="projects-title">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 id="projects-title">{tx("โปรเจกต์")}</h2>
              <Link href="/projects" className="btn small">{tx("ทั้งหมด")}</Link>
            </div>
            {projects === null ? <div className="empty">{tx("กำลังโหลด...")}</div>
              : projects.length === 0 ? <div className="empty">{tx("ยังไม่มีโปรเจกต์")}</div>
                : projects.slice(0, 4).map((p) => (
                  <Link key={p.id} href={`/projects/${p.id}`} className="dash-row">
                    <span className="dash-main">
                      <b>{p.name}</b>
                      <span>{tx("{0} ตอน", { 0: p.episodes })}{p.genre ? ` · ${p.genre}` : ""}</span>
                    </span>
                  </Link>
                ))}
          </section>
          <section className="card dash-block" aria-labelledby="shortcuts-title">
            <h2 id="shortcuts-title">{tx("ทางลัด")}</h2>
            <div className="dash-links">
              <Link href="/">{tx("ส่งคลิปใหม่")}</Link>
              <Link href="/timeline">{tx("นำเข้าไทม์ไลน์")} · {tx("อยู่ระหว่างพัฒนา")}</Link>
              <Link href="/voices">{tx("คลังเสียง")}</Link>
              {config?.billing && user && !user.admin && <Link href="/promotions">{tx("เติมเครดิต")}</Link>}
            </div>
          </section>
        </div>
      </div>}
    </main>
  );
}
