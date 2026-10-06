import { PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaPowerOff } from "react-icons/fa";

import { listDevices, type Device } from "./api";

function Content() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDevices()
      .then(setDevices)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  let body: string;
  if (error !== null) {
    body = `Could not load devices: ${error}`;
  } else if (devices === null) {
    body = "Loading…";
  } else if (devices.length === 0) {
    body = "No devices yet.";
  } else {
    body = `${devices.length} device(s) configured.`;
  }

  return (
    <PanelSection title="Devices">
      <PanelSectionRow>
        <div>{body}</div>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Wake Dispatch",
  titleView: <div className={staticClasses.Title}>Wake Dispatch</div>,
  content: <Content />,
  icon: <FaPowerOff />,
}));
