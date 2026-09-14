; The generated Tauri uninstaller checks shortcut targets only after deleting
; the application binary.  On some Windows shells, resolving that now-missing
; target can leave the silent NSIS second stage waiting indefinitely.  Remove
; only this product's exact shortcuts while the target still exists.
!macro NSIS_HOOK_PREUNINSTALL
  Delete "$SMPROGRAMS\${PRODUCTNAME}.lnk"
  Delete "$DESKTOP\${PRODUCTNAME}.lnk"

  ; /S hides the UI but does not set Tauri's separate /P passive flag.
  ; Ensure a successful silent uninstall cannot wait on a hidden finish page.
  IfSilent 0 +2
    SetAutoClose true
!macroend
