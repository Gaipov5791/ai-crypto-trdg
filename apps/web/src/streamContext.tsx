import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { connectMarketStream } from "./stream";
import type { WsEvent } from "./types";

type Listener = (event: WsEvent) => void;

type StreamApi = {
  connected: boolean;
  subscribe: (listener: Listener) => () => void;
};

const StreamContext = createContext<StreamApi | null>(null);

export function MarketStreamProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const listeners = useRef(new Set<Listener>());

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  useEffect(() => {
    return connectMarketStream({
      onStatus: setConnected,
      onEvent: (event) => {
        listeners.current.forEach((fn) => fn(event));
      },
    });
  }, []);

  return (
    <StreamContext.Provider value={{ connected, subscribe }}>
      {children}
    </StreamContext.Provider>
  );
}

export function useMarketStream(): StreamApi {
  const ctx = useContext(StreamContext);
  if (ctx == null) {
    throw new Error("useMarketStream must be used inside MarketStreamProvider");
  }
  return ctx;
}
