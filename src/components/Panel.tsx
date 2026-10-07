import { ButtonItem, Field, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { useEffect, useRef } from "react";

import { useTick } from "../hooks/useAutomationState";
import { useStatus } from "../hooks/useStatus";
import { useUpdate } from "../hooks/useUpdate";
import { ADD_DEVICE_FOCUS, loadDevices, useDevices, useFocusRequest, useWaking, wakeManual } from "../store";
import { S } from "../strings";
import { AccessibleText } from "./AccessibleText";
import { BackupModal } from "./BackupModal";
import { openDeviceEditor } from "./DeviceEditor";
import { DeviceRow } from "./DeviceRow";
import { EmptyState } from "./EmptyState";
import { focusSoon } from "./focus";
import { LastDispatch } from "./LastDispatch";
import { UpdateRow, UpdateSection } from "./UpdateSection";

/**
 * Quick Access panel: device rows (the first Wake takes focus), Add device, Wake
 * all when there are two or more devices, an "Update available" row when there
 * is one, the automatic-wake line, then the Updates and Backup sections.
 * With no devices, Add device is the first thing focused.
 */
export function Panel() {
  const { devices, failed } = useDevices();
  const list = devices ?? [];
  const statuses = useStatus(list.map((d) => d.id));
  const wakingAll = useWaking().all;
  const focus = useFocusRequest();
  const now = useTick(30_000);
  const update = useUpdate();
  const addRef = useRef<HTMLDivElement>(null);
  const loadedEmpty = devices !== null && devices.length === 0;
  const automationEnabled = list.some((d) => d.auto.length > 0);

  useEffect(() => {
    if (focus?.id === ADD_DEVICE_FOCUS) focusSoon(() => addRef.current, { retry: "always" });
  }, [focus?.seq]);

  // Kept enabled while sending (it may hold focus); wakeManual ignores repeats.
  const wakeAll = () => void wakeManual(null);

  return (
    <>
      <PanelSection title={S.devicesTitle} spinner={devices === null && !failed}>
        {failed && (
          <PanelSectionRow>
            <ButtonItem layout="below" description={S.loadFailed} onClick={() => void loadDevices()}>
              {S.tryAgain}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {devices === null && !failed && (
          <PanelSectionRow>
            <Field description={S.loading} bottomSeparator="none" focusable={false} />
          </PanelSectionRow>
        )}
        {loadedEmpty && (
          <PanelSectionRow>
            <EmptyState />
          </PanelSectionRow>
        )}
        {list.map((device) => (
          <PanelSectionRow key={device.id}>
            <DeviceRow device={device} status={statuses[device.id]} now={now} />
          </PanelSectionRow>
        ))}

        <PanelSectionRow>
          <div ref={addRef}>
            <ButtonItem layout="below" onClick={() => openDeviceEditor()}>
              {S.addDevice}
            </ButtonItem>
          </div>
        </PanelSectionRow>
        {list.length >= 2 && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={wakeAll}>
              <AccessibleText visible={wakingAll ? S.waking : S.wakeAll} label={wakingAll ? S.waking : S.wakeAllLabel} />
            </ButtonItem>
          </PanelSectionRow>
        )}
        <UpdateRow info={update.info} />
        {automationEnabled && (
          <PanelSectionRow>
            <LastDispatch devices={list} now={now} />
          </PanelSectionRow>
        )}
      </PanelSection>

      <UpdateSection update={update} />

      <PanelSection title={S.backupTitle}>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<BackupModal />)}>
            {S.backupEntry}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
