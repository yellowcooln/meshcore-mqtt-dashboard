/* Coalesce visual work only. Each caller still applies every data update. */
(() => {
  function createRenderScheduler(render, { intervalMs = 250 } = {}) {
    const pending = new Set();
    let timer = null;
    let lastPaint = -Infinity;
    let disposed = false;

    function schedule() {
      if (disposed || document.hidden || !pending.size || timer !== null) return;
      const delay = Math.max(0, intervalMs - (performance.now() - lastPaint));
      timer = setTimeout(flush, delay);
    }

    function flush() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      if (disposed || document.hidden || !pending.size) return;
      const sections = new Set(pending);
      pending.clear();
      lastPaint = performance.now();
      render(sections);
    }

    function request(...sections) {
      if (disposed) return;
      sections.forEach(section => pending.add(section));
      schedule();
    }

    function visibilityChanged() {
      if (document.hidden) {
        if (timer !== null) clearTimeout(timer);
        timer = null;
      } else {
        schedule();
      }
    }

    function dispose() {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pending.clear();
      document.removeEventListener("visibilitychange", visibilityChanged);
    }

    document.addEventListener("visibilitychange", visibilityChanged);
    return { request, flush, dispose };
  }

  window.DashboardUI = { createRenderScheduler };
})();
