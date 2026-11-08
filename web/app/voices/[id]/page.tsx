"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type LibraryVoice } from "@/lib/api";
import VoiceDetail from "@/components/VoiceDetail";
import { usePreview } from "@/components/VoicePreview";
import { ArrowLeft } from "@/components/Icons";
import { useAuth } from "@/lib/useAuth";
import { tx } from "@/lib/i18n";

export default function VoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const preview = usePreview();
  const { config, user, loaded } = useAuth();
  const [voice, setVoice] = useState<LibraryVoice | null>(null);
  const [known, setKnown] = useState<string[]>([]);
  const [error, setError] = useState("");

  const canEdit = loaded && (!!user?.admin || !!voice?.mine || !config?.auth);

  const refresh = useCallback(() => {
    if (!id) return;
    api.getVoice(id)
      .then((v) => { setVoice(v); setError(""); })
      .catch((e) => {
        setError(e.message);
        setVoice(null);
      });
  }, [id]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    api.listVoices().then((list) => {
      const count = new Map<string, number>();
      list.forEach((v) => (v.categories ?? []).forEach((c) => count.set(c, (count.get(c) ?? 0) + 1)));
      setKnown([...count.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c));
    }).catch(() => undefined);
  }, []);

  const processing = useMemo(
    () => !!voice && (voice.status === "processing" || voice.moods.some((m) => m.status === "processing")),
    [voice],
  );
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [processing, refresh]);

  const onChanged = () => {
    // ลบแล้วกลับรายการ
    api.getVoice(id).then(setVoice).catch(() => router.replace("/voices"));
  };

  return (
    <main className="page" style={{ maxWidth: 1040 }}>
      <div className="row" style={{ gap: 10, marginBottom: 8 }}>
        <Link href="/voices" className="btn small" aria-label={tx("กลับหน้าคลังเสียง")}><ArrowLeft /> {tx("คลังเสียง")}</Link>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!voice && !error && <div className="empty">{tx("กำลังโหลด...")}</div>}
      {voice && (
        <VoiceDetail v={voice} preview={preview} onChanged={onChanged} known={known} canEdit={canEdit} />
      )}
    </main>
  );
}
