// ไอคอนเส้นแบบเรียบ ใช้ซ้ำทั้งแอป

type P = { size?: number; color?: string };

const svg = (size: number, color: string, children: React.ReactNode) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

export const MicIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" /><path d="M19 11a7 7 0 0 1-14 0" /><path d="M12 18v3" /></>);

export const UploadIcon = ({ size = 28, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></>);

export const LinkIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" /></>);

export const ArrowRight = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></>);

export const ArrowLeft = ({ size = 18, color = "currentColor" }: P) => svg(size, color, <path d="M15 6l-6 6 6 6" />);

export const CheckIcon = ({ size = 15, color = "currentColor" }: P) => svg(size, color, <path d="M5 12l5 5 9-10" />);

export const DownloadIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M12 4v12" /><path d="M7 11l5 5 5-5" /><path d="M5 20h14" /></>);

export const PlusIcon = ({ size = 16, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M12 5v14" /><path d="M5 12h14" /></>);

export const SearchIcon = ({ size = 16, color = "currentColor" }: P) =>
  svg(size, color, <><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>);

export const PlayIcon = ({ size = 15 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" />
  </svg>
);

export const PauseIcon = ({ size = 15, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M8 5v14" /><path d="M16 5v14" /></>);

export const ScissorsIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M20 4L8.1 15.9" /><path d="M14.5 14.5L20 20" /><path d="M8.1 8.1L12 12" /></>);

export const MergeIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M7 4v5a5 5 0 0 0 5 5 5 5 0 0 1 5 5v1" /><path d="M17 4v5a5 5 0 0 1-3 4.6" /></>);

export const XIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M6 6l12 12" /><path d="M18 6L6 18" /></>);
