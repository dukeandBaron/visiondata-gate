/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_VISIONDATA_API_BASE_URL?: string;
  readonly VITE_VISIONDATA_REVIEWER_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
