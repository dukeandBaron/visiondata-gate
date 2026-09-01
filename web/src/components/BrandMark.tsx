export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand-mark${compact ? " is-compact" : ""}`} aria-label="VisionData Gate">
      <span className="brand-mark__glyph" aria-hidden="true">
        <svg viewBox="0 0 36 36" role="img">
          <path d="M18 2.5 31 7v9.8c0 8.1-5.2 13.7-13 16.7C10.2 30.5 5 24.9 5 16.8V7l13-4.5Z" />
          <path d="m11.4 12.2 6.6 13 6.6-13h-4.1L18 17.8l-2.5-5.6h-4.1Z" />
        </svg>
      </span>
      {!compact ? (
        <span className="brand-mark__copy">
          <strong>VisionData Gate</strong>
          <small>Industrial Data Release</small>
        </span>
      ) : null}
    </div>
  );
}
