-- คะแนนงานอัตโนมัติรายวัน (app/daily_metrics.py / job_metrics.py)
-- รันทุก 23:59 Asia/Bangkok เก็บ snapshot ให้ AI เทียบก่อน/หลังแก้โค้ด
-- ต่างจาก job_quality ที่วัดจากคนแก้บท

-- งานละแถวต่อวันรัน
create table if not exists job_metric_scores (
  run_date              date not null,
  job_id                text not null,
  n_lines               integer not null default 0,
  speakers              text[] not null default '{}',
  overall               double precision,
  speech_coverage       double precision,
  dub_match             double precision,
  timing_fit            double precision,
  length_vs_source      double precision,
  translate_fidelity    double precision,
  prosody_match         double precision,
  lip_overflow          double precision,
  term_consistency      double precision,
  speaker_confusion     double precision,
  needs_asr_heal        boolean not null default false,
  metrics               jsonb not null default '{}'::jsonb,
  created_at            timestamptz not null default now(),
  primary key (run_date, job_id)
);
create index if not exists job_metric_scores_run on job_metric_scores (run_date desc);
create index if not exists job_metric_scores_overall on job_metric_scores (run_date, overall);

-- สรุปวันละแถว
create table if not exists job_metric_daily (
  run_date              date primary key,
  n_jobs                integer not null default 0,
  needs_heal            integer not null default 0,
  mean_overall          double precision,
  mean_coverage         double precision,
  mean_dub_match        double precision,
  mean_timing           double precision,
  mean_length           double precision,
  mean_translate        double precision,
  mean_prosody          double precision,
  mean_lip              double precision,
  mean_terms            double precision,
  mean_speaker          double precision,
  worst_job_id          text not null default '',
  summary               jsonb not null default '{}'::jsonb,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
create index if not exists job_metric_daily_updated on job_metric_daily (updated_at desc);

alter table job_metric_scores enable row level security;
alter table job_metric_daily enable row level security;
