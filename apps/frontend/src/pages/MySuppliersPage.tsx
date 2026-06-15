import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { supplierWorkflowService } from "@/services/api";
import type { Supplier } from "@/types";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MapPin, ShieldCheck, Bookmark, ExternalLink } from "lucide-react";

export default function MySuppliersPage() {
  const { t } = useTranslation();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchMyList = async () => {
      try {
        const res = await supplierWorkflowService.getMyList();
        setSuppliers(res.data.items);
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoading(false);
      }
    };
    fetchMyList();
  }, []);

  const approved = suppliers.filter(s => s.status === 'approved');
  const saved = suppliers.filter(s => s.status === 'saved');

  if (isLoading) {
    return <div className="p-8 text-center text-muted-foreground">Loading your suppliers...</div>;
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8 animate-in fade-in duration-500">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">My Suppliers</h1>
        <p className="text-muted-foreground">
          Manage your personal shortlist and view company-approved vendors.
        </p>
      </div>

      <Tabs defaultValue="approved" className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="approved" className="gap-2">
            <ShieldCheck className="w-4 h-4" />
            Approved Vendors ({approved.length})
          </TabsTrigger>
          <TabsTrigger value="saved" className="gap-2">
            <Bookmark className="w-4 h-4" />
            My Shortlist ({saved.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="approved" className="space-y-4">
          {approved.length === 0 ? (
            <div className="text-center p-12 bg-muted/30 rounded-xl border border-dashed">
              <ShieldCheck className="w-12 h-12 text-muted-foreground/50 mx-auto mb-4" />
              <h3 className="text-lg font-medium">No approved suppliers yet</h3>
              <p className="text-muted-foreground text-sm mt-1">Discover new suppliers and ask a manager to approve them.</p>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {approved.map(s => <SimpleSupplierCard key={s.id} supplier={s} />)}
            </div>
          )}
        </TabsContent>

        <TabsContent value="saved" className="space-y-4">
          {saved.length === 0 ? (
            <div className="text-center p-12 bg-muted/30 rounded-xl border border-dashed">
              <Bookmark className="w-12 h-12 text-muted-foreground/50 mx-auto mb-4" />
              <h3 className="text-lg font-medium">Your shortlist is empty</h3>
              <p className="text-muted-foreground text-sm mt-1">Run a search and click "Save to Shortlist" to add suppliers here.</p>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {saved.map(s => <SimpleSupplierCard key={s.id} supplier={s} />)}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SimpleSupplierCard({ supplier }: { supplier: Supplier }) {
  return (
    <Card className="hover:shadow-md transition-all">
      <CardHeader className="pb-3 flex flex-row items-start justify-between">
        <div>
          <h3 className="font-semibold text-lg">{supplier.name}</h3>
          <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
            {supplier.city && (
              <span className="flex items-center gap-1">
                <MapPin className="w-3.5 h-3.5" />
                {supplier.city}{supplier.country ? `, ${supplier.country}` : ""}
              </span>
            )}
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
          {supplier.website && (
             <Button variant="ghost" size="sm" asChild className="h-8 text-xs gap-1">
               <a href={supplier.website} target="_blank" rel="noreferrer">
                 Site <ExternalLink className="w-3 h-3" />
               </a>
             </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
