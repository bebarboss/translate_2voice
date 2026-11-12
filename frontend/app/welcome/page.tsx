"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import "@fontsource/ibm-plex-sans-thai/300.css";
import "@fontsource/ibm-plex-sans-thai/700.css";
import { BrandLink, BRAND_NAME } from "@/components/Brand";
import { MicIcon } from "@/components/Icons";
import { useAuth } from "@/lib/useAuth";
import { signInPath } from "@/lib/auth-routes";
import { chooseLang, getLang, tx } from "@/lib/i18n";
/** หน้าแรกก่อนเข้าสู่ระบบ: บอกว่าระบบทำอะไร แล้วพาไปสมัครหรือเข้าสู่ระบบ */

const LANES = [
  { name: "โนบิตะ", color: "#6AB0FF", blocks: [[2, 14], [22, 34], [58, 71], [86, 95]] },
  { name: "โดราเอมอน", color: "#4FD1B5", blocks: [[15, 21], [36, 52], [73, 84]] },
  { name: "ชิซุกะ", color: "#C99BFF", blocks: [[44, 57], [64, 72]] },
];
const LINES = [
  { who: "โนบิตะ", color: "#6AB0FF", text: "ทำการบ้านให้เสร็จก่อน แล้วไปแคมป์กันนะ!" },
  { who: "โดราเอมอน", color: "#4FD1B5", text: "เอาล่ะ ออกเดินทางไปผจญภัยใต้ทะเลกันเลย" },
  { who: "ชิซุกะ", color: "#C99BFF", text: "มีแต่เรื่องแปลก ๆ อยากไขปริศนาด้วยกันไหม?" },
];

const FEATURES = [
  { title: "แยกเสียงตัวละครให้เอง", text: "แยกเสียงพูดออกจากเพลง แล้วจัดกลุ่มว่าใครพูดประโยคไหน โดยไม่ต้องบอกจำนวนคน" },
  { title: "แปลให้พอดีปาก", text: "แปลตามแนวเรื่องและชื่อตัวละคร ย่อบทให้พูดทันเวลา ไม่ต้องเร่งเสียงจนรีบ" },
  { title: "เสียงพากย์จากคลังของคุณ", text: "เลียนเสียงนักแสดงต้นฉบับ หรือเลือกเสียงพากย์ไทยจากคลัง พร้อมเสียงหลายอารมณ์" },
  { title: "แก้บนไทม์ไลน์", text: "ลาก ตัด คัดลอกประโยค วางเสียงซ้อนกัน แล้วพากย์ใหม่เฉพาะตรงที่แก้" },
];

const STEPS = [
  { n: "1", title: "ส่งคลิป", text: "อัปโหลดไฟล์ หรือวางลิงก์ YouTube, TikTok, Facebook" },
  { n: "2", title: "ตรวจบท", text: "ฟัง ดู และแก้บทแปลกับตัวละครก่อนพากย์" },
  { n: "3", title: "ได้คลิปพากย์", text: "ดาวน์โหลดวิดีโอพากย์ไทย พร้อมซับและเลเยอร์เสียงแยก" },
];

function Demo() {
  const [t, setT] = useState(0); // 0–100 ตำแหน่งหัวอ่าน
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setT(30); return; }
    const id = window.setInterval(() => setT((x) => (x + 0.25) % 100), 40);
    return () => window.clearInterval(id);
  }, []);
  const line = LINES[Math.floor(t / 34) % LINES.length];
  return (
    <div className="lp-demo" aria-hidden="true">
      <div className="lp-demo-bar"><span /><span /><span /><em>{BRAND_NAME}</em></div>
      <div className="lp-demo-video">
        <div className="lp-demo-caption"><b style={{ color: line.color }}>{tx(line.who)}</b> {tx(line.text)}</div>
      </div>
      <div className="lp-demo-lanes">
        {LANES.map((l) => (
          <div key={l.name} className="lp-lane">
            <span className="lp-lane-name"><i style={{ background: l.color }} />{tx(l.name)}</span>
            <div className="lp-track">
              {l.blocks.map(([a, b]) => (
                <span key={a} style={{ left: `${a}%`, width: `${b - a}%`, background: l.color, opacity: t >= a && t <= b ? 1 : 0.4 }} />
              ))}
              <div className="lp-playhead" style={{ left: `${t}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function WelcomePage() {
  const { config, user } = useAuth();
  const [next, setNext] = useState("/dashboard");
  useEffect(() => {
    const n = new URLSearchParams(window.location.search).get("next") ?? "/dashboard";
    setNext(n.startsWith("/") && !n.startsWith("//") ? n : "/dashboard");
  }, []);
  const authOn = !!config?.auth;
  const signedIn = !!user;
  const start = !authOn || signedIn ? next : signInPath(next.startsWith("/") ? next : "/dashboard", "", { signup: true });
  const login = signInPath(next.startsWith("/") ? next : "/dashboard");
  // ปุ่มสมัครนักพากย์ต้องไปหน้าสมัครโดยตรง ถ้าชี้ไป /actor ผู้ที่ยังไม่ล็อกอินจะถูกเด้งแล้วกลับมาหน้านี้เงียบ ๆ
  const actorHref = !authOn || signedIn ? "/actor" : signInPath("/actor");

  return (
    <div className="landing">
      <div className="lp-glow" aria-hidden="true" />
      <header className="lp-nav">
        <BrandLink href="/welcome" className="lp-brand" markClassName="lp-brand-mark" markSize={28} />
        <nav aria-label={tx("เมนูหน้าแรก")}>
          <a href="#features">{tx("ความสามารถ")}</a>
          <a href="#actors">{tx("นักพากย์")}</a>
          <a href="#how">{tx("วิธีใช้")}</a>
          <button type="button" className="lp-lang" lang={getLang() === "th" ? "en" : "th"}
            onClick={() => chooseLang(getLang() === "th" ? "en" : "th")}>{getLang() === "th" ? "English" : "ไทย"}</button>
          {authOn && !signedIn
            ? <Link href={login} className="lp-pill lp-pill-accent">{tx("เข้าสู่ระบบ")}</Link>
            : <Link href={next} className="lp-pill lp-pill-accent">{tx("เข้าสตูดิโอ")}</Link>}
        </nav>
      </header>

      <main>
        <section className="lp-hero">
          <div className="lp-hero-copy">
            <p className="lp-kicker">{BRAND_NAME}</p>
            <h1>
              <span className="lp-h-bold">{tx("พากย์ดี")}</span>
              <span className="lp-h-thin">{tx("ด้วย AI")}</span>
            </h1>
            <p className="lp-tagline">{tx("นกแก้วช่วยแยกตัวละคร แปล และพากย์คลิปต่างประเทศเป็นไทย")}</p>
            <div className="lp-cta">
              <Link href={start} className="lp-pill lp-pill-dark lp-pill-lg">
                <MicIcon size={18} color="#fff" /> {signedIn || !authOn ? tx("เริ่มพากย์คลิป") : tx("เริ่มพากย์คลิปแรก")}
              </Link>
              {authOn && !signedIn
                ? <Link href={login} className="lp-pill lp-pill-light lp-pill-lg">{tx("เข้าสู่ระบบ")}</Link>
                : <a href="#how" className="lp-pill lp-pill-light lp-pill-lg">{tx("ดูวิธีใช้")}</a>}
            </div>
            <p className="lp-note">{tx("รองรับคลิปภาษาจีน ญี่ปุ่น เกาหลี อังกฤษ และอีกหลายภาษา · พากย์เป็นไทยหรืออังกฤษ")}</p>
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="lp-hero-mascot"
            src="/brand/mascot.png"
            alt={BRAND_NAME}
            width={860}
            height={980}
          />
          <Demo />
        </section>

        <section id="features" className="lp-section">
          <h2>{tx("ทุกขั้นของงานพากย์ ในที่เดียว")}</h2>
          <div className="lp-grid">
            {FEATURES.map((f) => (
              <article key={f.title} className="lp-card">
                <h3>{tx(f.title)}</h3>
                <p>{tx(f.text)}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="actors" className="lp-section lp-actors">
          <div className="lp-actors-copy">
            <p className="lp-actors-kicker">{tx("สำหรับนักพากย์")}</p>
            <h2>{tx("ให้เสียงของคุณช่วยพากย์คลิปบนพากย์ดี")}</h2>
            <p className="lp-actors-lead">
              {tx("สมัครส่งเสียงเข้าคลัง ได้ค่าตอบแทนเมื่อมีคนใช้เสียงของคุณพากย์ — นกแก้วพากย์ดีพร้อมต้อนรับ")}
            </p>
            <div className="lp-cta">
              <Link href={actorHref} className="lp-pill lp-pill-dark lp-pill-lg">
                <MicIcon size={18} color="#fff" /> {tx("สมัครเป็นนักพากย์")}
              </Link>
            </div>
          </div>
          <div className="lp-actors-media">
            <video
              className="lp-actors-video"
              src="/brand/voice-actor-recruit.mp4"
              poster="/brand/voice-actor-recruit.jpg"
              width={720}
              height={1280}
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              aria-label={tx("คลิปชวนสมัครนักพากย์พากย์ดี")}
            />
          </div>
        </section>

        <section id="how" className="lp-section">
          <h2>{tx("สามขั้นตอน")}</h2>
          <ol className="lp-steps">
            {STEPS.map((s) => (
              <li key={s.n}>
                <span className="lp-step-n">{s.n}</span>
                <h3>{tx(s.title)}</h3>
                <p>{tx(s.text)}</p>
              </li>
            ))}
          </ol>
          <div className="lp-cta" style={{ justifyContent: "center" }}>
            <Link href={start} className="lp-pill lp-pill-dark lp-pill-lg">{tx("เริ่มเลย")}</Link>
          </div>
        </section>
      </main>

      <footer className="lp-footer">© {new Date().getFullYear()}  {tx("Pakdee · ใช้กับคลิปที่คุณมีสิทธิ์และเสียงที่ได้รับอนุญาตเท่านั้น")}</footer>
    </div>
  );
}
