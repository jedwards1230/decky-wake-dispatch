import { ButtonItem, PanelSection, PanelSectionRow, showModal } from "@decky/ui";

import { useStatus } from "../hooks/useStatus";
import { loadDevices, useDevices, useWaking, wakeManual } from "../store";
import { S } from "../strings";
import { AccessibleText } from "./AccessibleText";
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
  const wakingAll = useWaking().all;
  const loadedEmpty = devices !== null && devices.length === 0;
  const automationEnabled = list.some((d) => d.auto.length > 0);

  // wakeManual ignores a second press while Wake all is in flight.
  const wakeAll = () => {
    if (list.length > 0) void wakeManual(null);
  };

  return (
    <>
      <PanelSection title={S.devicesTitle} spinner={devices === null && !failed}>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={list.length === 0 || wakingAll}
            description={loadedEmpty ? S.wakeAllNoDevices : undefined}
            onClick={wakeAll}
          >
            <AccessibleText visible={wakingAll ? S.waking : S.wakeAll} label={wakingAll ? S.waking : S.wakeAllLabel} />
          </ButtonItem>
        </PanelSectionRow>

        {failed && (
          <PanelSectionRow>
            <ButtonItem layout="below" description={S.loadFailed} onClick={() => void loadDevices()}>
              {S.tryAgain}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {devices === null && !failed && (
          <PanelSectionRow>
            <div style={{ fontSize: "13px" }}>{S.loading}</div>
          </PanelSectionRow>
        )}
        {loadedEmpty && (
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
        {automationEnabled && (
          <PanelSectionRow>
            <LastDispatch />
          </PanelSectionRow>
        )}
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
