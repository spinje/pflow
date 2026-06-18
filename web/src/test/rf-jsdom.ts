// React Flow needs a handful of browser APIs that jsdom does not implement
// (ResizeObserver, DOMMatrixReadOnly, getBoundingClientRect with real numbers,
// matchMedia). This is the documented minimal mock set so a graph can mount in a
// jsdom test. Call installReactFlowJsdomMocks() in beforeAll.

export function installReactFlowJsdomMocks(): void {
  class ResizeObserverMock {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  Object.assign(globalThis, {
    ResizeObserver: ResizeObserverMock,
    DOMMatrixReadOnly: class {
      m22 = 1;
      constructor(_t?: string) {}
    },
  });

  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });

  Element.prototype.getBoundingClientRect = function (): DOMRect {
    return {
      x: 0,
      y: 0,
      width: 220,
      height: 60,
      top: 0,
      left: 0,
      right: 220,
      bottom: 60,
      toJSON: () => ({}),
    } as DOMRect;
  };
}
