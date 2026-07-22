import { useState, useEffect } from "react";
import { supplierWorkflowService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";
import { canModerate } from "@/lib/utils";
import type { Supplier } from "@/types";
import { formatSupplierLocation } from "@/features/suppliers/location";
import { JustificationDialog } from "@/features/suppliers/JustificationDialog";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MapPin, ShieldCheck, Bookmark, ExternalLink, AlertCircle, Trash2 } from "lucide-react";

type Decision = { supplier: Supplier; action: "approve" | "reject" };

export default function MySuppliersPage() {
  const user = useAuthStore((s) => s.user);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [pending, setPending] = useState<Supplier[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Approve/reject is manager-gated (admin OR procurement_manager); analysts
  // see the Pending Review tab read-only.
  const userCanModerate = canModerate(user);

  // Justification dialog state (shared JustificationDialog owns the form).
  const [decision, setDecision] = useState<Decision | null>(null);

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [myList, pendingRes] = await Promise.all([
          supplierWorkflowService.getMyList(),
          supplierWorkflowService.getPending(),
        ]);
        setSuppliers(myList.data.items);
        setPending(pendingRes.data.items);
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoading(false);
      }
    };
    fetchAll();
  }, []);

  const saved = suppliers.filter((s) => s.status === "saved");

  const submitDecision = async (text: string) => {
    if (!decision) return;
    const { supplier, action } = decision;
    if (action === "approve") {
      await supplierWorkflowService.approve(supplier.id, text);
    } else {
      await supplierWorkflowService.reject(supplier.id, text);
    }
    setPending((prev) => prev.filter((s) => s.id !== supplier.id));
  };

  if (isLoading) {
    return <div className="p-8 text-center text-muted-foreground">Loading your suppliers...</div>;
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8 animate-in fade-in duration-500">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">My Suppliers</h1>
        <p className="text-muted-foreground">
          Manage your personal shortlist and review web-discovered suppliers.
        </p>
      </div>

      <Tabs defaultValue="saved" className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="saved" className="gap-2">
            <Bookmark className="w-4 h-4" />
            My Shortlist ({saved.length})
          </TabsTrigger>
          <TabsTrigger value="pending" className="gap-2">
            <AlertCircle className="w-4 h-4" />
            Pending Review ({pending.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="saved" className="space-y-4">
          {saved.length === 0 ? (
            <div className="text-center p-12 bg-muted/30 rounded-xl border border-dashed">
              <Bookmark className="w-12 h-12 text-muted-foreground/50 mx-auto mb-4" />
              <h3 className="text-lg font-medium">Your shortlist is empty</h3>
              <p className="text-muted-foreground text-sm mt-1">Run a search and click "Save to Shortlist" to add suppliers here.</p>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {saved.map((s) => <SimpleSupplierCard key={s.id} supplier={s} />)}
            </div>
          )}
        </TabsContent>

        <TabsContent value="pending" className="space-y-4">
          {pending.length === 0 ? (
            <div className="text-center p-12 bg-muted/30 rounded-xl border border-dashed">
              <AlertCircle className="w-12 h-12 text-muted-foreground/50 mx-auto mb-4" />
              <h3 className="text-lg font-medium">Nothing awaiting review</h3>
              <p className="text-muted-foreground text-sm mt-1">Web-discovered suppliers appear here until a manager approves or rejects them.</p>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {pending.map((s) => (
                <SimpleSupplierCard
                  key={s.id}
                  supplier={s}
                  pending
                  canModerate={userCanModerate}
                  onApprove={() => setDecision({ supplier: s, action: "approve" })}
                  onReject={() => setDecision({ supplier: s, action: "reject" })}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* HITL justification dialog — shared with SupplierCard's approve/reject flow */}
      <JustificationDialog
        action={decision?.action ?? null}
        supplierName={decision?.supplier.name}
        onClose={() => setDecision(null)}
        onSubmit={submitDecision}
      />
    </div>
  );
}

function SimpleSupplierCard({
  supplier,
  pending = false,
  canModerate = false,
  onApprove,
  onReject,
}: {
  supplier: Supplier;
  pending?: boolean;
  canModerate?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
}) {
  const location = formatSupplierLocation(supplier.city, supplier.country);

  return (
    <Card className="hover:shadow-md transition-all">
      <CardHeader className="pb-3 flex flex-row items-start justify-between">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-lg">{supplier.name}</h3>
            {pending && (
              <Badge variant="outline" className="text-xs border-amber-200 bg-amber-50 text-amber-700 gap-1">
                <AlertCircle className="w-3 h-3" />
                Pending Review
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
            {location ? (
              <span className="flex items-center gap-1">
                <MapPin className="w-3.5 h-3.5" />
                {location}
              </span>
            ) : pending ? (
              <span className="flex items-center gap-1">
                <MapPin className="w-3.5 h-3.5" />
                Location not verified
              </span>
            ) : null}
            <Badge variant="outline" className="text-xs font-normal">
              {supplier.category || 'General'}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {supplier.description && (
          <p className="text-sm text-muted-foreground line-clamp-3 mb-4">
            {supplier.description}
          </p>
        )}
        <div className="flex items-center justify-between mt-auto pt-2 border-t border-border/50">
          <div className="flex gap-2">
            {supplier.certifications?.slice(0,2).map(c => (
              <Badge key={c} variant="secondary" className="text-[10px] py-0">{c}</Badge>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {supplier.website && (
               <Button variant="ghost" size="sm" asChild className="h-8 text-xs gap-1">
                 <a href={supplier.website} target="_blank" rel="noreferrer">
                   Site <ExternalLink className="w-3 h-3" />
                 </a>
               </Button>
            )}
            {pending && canModerate && (
              <>
                <Button
                  variant="default"
                  size="sm"
                  className="h-8 text-xs gap-1.5"
                  onClick={onApprove}
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  Approve
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={onReject}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Reject
                </Button>
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
