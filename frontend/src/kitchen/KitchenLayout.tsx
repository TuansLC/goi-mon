/**
 * Kitchen layout wrapper — provides auth context to all kitchen routes.
 */

import { Outlet } from "react-router-dom";
import { KitchenAuthProvider } from "./AuthContext";

export default function KitchenLayout() {
  return (
    <KitchenAuthProvider>
      <Outlet />
    </KitchenAuthProvider>
  );
}
