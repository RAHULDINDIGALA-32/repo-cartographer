export function createTokenBatcher(flush: (text: string) => void) {
  let pending = "";
  let frame: number | undefined;
  const flushPending = () => {
    frame = undefined;
    if (pending) {
      const value = pending;
      pending = "";
      flush(value);
    }
  };
  return {
    push(text: string) {
      pending += text;
      if (frame === undefined) frame = requestAnimationFrame(flushPending);
    },
    flush() {
      if (frame !== undefined) cancelAnimationFrame(frame);
      flushPending();
    },
    dispose() {
      if (frame !== undefined) cancelAnimationFrame(frame);
      pending = "";
      frame = undefined;
    },
  };
}
