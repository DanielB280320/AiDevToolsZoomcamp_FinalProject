import { useEffect, useState } from "react";

/**
 * Returns `focus(id)`: moves keyboard focus to the element with that id after the next render,
 * once error messages and `aria-invalid` are in the DOM, so screen readers announce them.
 */
export function useFocusAfterRender(): (id: string) => void {
  const [request, setRequest] = useState<{ id: string; seq: number } | null>(null);

  useEffect(() => {
    if (request) document.getElementById(request.id)?.focus();
  }, [request]);

  return (id: string) => setRequest((previous) => ({ id, seq: (previous?.seq ?? 0) + 1 }));
}
