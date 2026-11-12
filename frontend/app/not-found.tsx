import Link from "next/link";

/** เส้นทางที่ไม่มีในแอป ไม่ถูก proxy พาไปเข้าสู่ระบบ */
export default function NotFound() {
  return (
    <main className="page narrow">
      <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600 }}>ไม่พบหน้านี้</h1>
      <p className="muted" style={{ margin: 0 }}>
        ลิงก์อาจผิด หรือหน้านี้ถูกย้ายแล้ว
      </p>
      <p className="dim" style={{ margin: 0 }}>Page not found.</p>
      <div className="row">
        <Link href="/welcome" className="btn primary">กลับหน้าแรก</Link>
      </div>
    </main>
  );
}
