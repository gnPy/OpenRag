"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/settings-tabs";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";

const TABS = [
  { value: "connectors", label: "Connectors" },
  { value: "providers", label: "Providers", perm: "providers:write" },
  { value: "langflow", label: "Langflow" },
  { value: "api-keys", label: "API Keys", apiKeysTab: true },
  { value: "roles", label: "Roles & Permissions", rbacPerm: "users:list" },
] as const;

export function SettingsNav() {
  const isCloudBrand = useIsCloudBrand();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode, rbacEnforced } =
    useAuth();
  const { can } = usePermissions();

  const currentTab = pathname.split("/").pop() ?? "connectors";
  const [previousTab, setPreviousTab] = useState<string | null>(null);
  const lastTabRef = useRef(currentTab);

  useEffect(() => {
    const last = lastTabRef.current;
    if (last !== currentTab) {
      setPreviousTab(last);
      lastTabRef.current = currentTab;
    }
  }, [currentTab]);

  const visibleTabs = TABS.filter((tab) => {
    if ("perm" in tab) return can(tab.perm);
    if ("apiKeysTab" in tab)
      return (isAuthenticated || isNoAuthMode) && !isIbmAuthMode;
    if ("rbacPerm" in tab) return rbacEnforced && can(tab.rbacPerm);
    return true;
  });

  const handleTabClick = (tabValue: string) => {
    if (isCloudBrand && tabValue !== currentTab) {
      setPreviousTab(currentTab);
    }
    router.push(`/settings/${tabValue}`);
  };

  if (!isCloudBrand) {
    return (
      <Tabs value={currentTab}>
        <TabsList className="mb-6 p-2 rounded-full">
          {visibleTabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              onClick={() => router.push(`/settings/${tab.value}`)}
              className="p-3 rounded-full"
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    );
  }

  return (
    <Tabs value={currentTab}>
      <TabsList variant="ibm">
        {visibleTabs.map((tab) => (
          <TabsTrigger
            key={tab.value}
            variant="ibm"
            value={tab.value}
            onClick={() => handleTabClick(tab.value)}
            className={cn(
              tab.value === previousTab &&
                tab.value !== currentTab &&
                "ibm-tab-underline--previous",
            )}
          >
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
