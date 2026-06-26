"use client";

import { useState, useCallback, useMemo, useContext, createContext, useRef } from "react";
import { Alert, Snackbar } from "@mui/material";

type NotificationType = "success" | "error" | "warning" | "info";

interface Notification {
  id: string;
  type: NotificationType;
  message: string;
  duration?: number;
  position: number;
}

interface NotificationContextValue {
  notify: (notification: Omit<Notification, "id" | "position">) => void;
  closeNotification: (id: string) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const positionRef = useRef(0);

  const notify = useCallback((notification: Omit<Notification, "id" | "position">) => {
    const position = positionRef.current++;
    setNotifications((prev) => [...prev, { ...notification, id: generateId(), position }]);
  }, []);

  const closeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const value = useMemo(
    () => ({ notify, closeNotification }),
    [notify, closeNotification]
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
      {notifications.map((notification) => (
        <Snackbar
          key={notification.id}
          open
          autoHideDuration={notification.duration ?? 5000}
          onClose={() => closeNotification(notification.id)}
          anchorOrigin={{ vertical: "top", horizontal: "right" }}
          sx={{ mt: notification.position * 1.5 }}
        >
          <Alert
            severity={notification.type}
            onClose={() => closeNotification(notification.id)}
            sx={{ width: "100%" }}
          >
            {notification.message}
          </Alert>
        </Snackbar>
      ))}
    </NotificationContext.Provider>
  );
}

export function useNotification() {
  const ctx = useContext(NotificationContext);
  if (!ctx) {
    throw new Error("useNotification must be used within NotificationProvider");
  }
  return ctx;
}
