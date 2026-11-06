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

export const ShuffleIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M16 3h5v5" /><path d="M4 20L21 3" /><path d="M21 16v5h-5" /><path d="M15 15l6 6" /><path d="M4 4l5 5" /></>);

export const XIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M6 6l12 12" /><path d="M18 6L6 18" /></>);

export const CopyIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>);

export const PasteIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><rect x="6" y="4" width="12" height="17" rx="2" /><path d="M9 4V3h6v1" /><path d="M9 10h6" /><path d="M9 14h6" /></>);

export const TrashIcon = ({ size = 14, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="M6 7l1 13h10l1-13" /></>);

export const GridIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M4 4h7v7H4z" /><path d="M13 4h7v7h-7z" /><path d="M4 13h7v7H4z" /><path d="M13 13h7v7h-7z" /></>);

export const ListIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M9 6h11" /><path d="M9 12h11" /><path d="M9 18h11" /><path d="M4 6h.01" /><path d="M4 12h.01" /><path d="M4 18h.01" /></>);

export const WaveIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M4 10v4" /><path d="M8 6v12" /><path d="M12 3v18" /><path d="M16 7v10" /><path d="M20 10v4" /></>);

export const GearIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>);

export const UserIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>);

export const MenuIcon = ({ size = 20, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /></>);

export const TagIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z" /><path d="M7.5 7.5h.01" /></>);

export const ShieldIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></>);

export const FolderIcon = ({ size = 18, color = "currentColor" }: P) =>
  svg(size, color, <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />);
