import { ButtonItem, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { useState } from "react";

import { useStatus } from "../hooks/useStatus";
import { useDevices, wakeManual } from "../store";
import { S } from "../strings";
import { DeviceEditor } from "./DeviceEditor";
import { DeviceRow } from "./DeviceRow";
import { EmptyState } from "./EmptyState";
import { ExportModal } from "./ExportModal";
import { ImportModal } from "./ImportModal";
import { LastDispatch } from "./LastDispatch";

/** Quick Access panel: Wake all, device rows, Add device, last automatic wake, backup. */
export function Panel() {
  const { devices, failed } = useDevices();
  const list = devices ?? [];
  const statuses = useStatus(list.map((d) => d.id));
  const [wakingAll, setWakingAll] = useState(false);
  const automationEnabled = list.some((d) => d.auto.length > 0);

  const wakeAll = async () => {
    if (wakingAll || list.length === 0) return;
    setWakingAll(true);
    try {
      await wakeManual(null);
    } finally {
      setWakingAll(false);
    }
  };

  return (
    <>
      <PanelSection title={S.devicesTitle} spinner={devices === null && !failed}>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={list.length === 0}
            description={list.length === 0 ? S.wakeAllNoDevices : undefined}
            onClick={() => void wakeAll()}
          >
            {wakingAll ? S.waking : S.wakeAll}
          </ButtonItem>
        </PanelSectionRow>

        {failed && (
          <PanelSectionRow>
            <div style={{ fontSize: "13px" }}>{S.loadFailed}</div>
          </PanelSectionRow>
        )}
        {devices === null && !failed && (
          <PanelSectionRow>
            <div style={{ fontSize: "13px" }}>{S.loading}</div>
          </PanelSectionRow>
        )}
        {devices !== null && devices.length === 0 && (
          <PanelSectionRow>
            <EmptyState />
          </PanelSectionRow>
        )}
        {list.map((device) => (
          <PanelSectionRow key={device.id}>
            <DeviceRow device={device} status={statuses[device.id]} />
          </PanelSectionRow>
        ))}

        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<DeviceEditor />)}>
            {S.addDevice}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <LastDispatch automationEnabled={automationEnabled} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={S.backupTitle}>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<ExportModal />)}>
            {S.exportSettings}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<ImportModal />)}>
            {S.importSettings}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
